"""
Google Calendar OAuth endpoints — /api/v1/calendar

GET  /calendar/auth      -> returns the Google consent URL for this user to visit
GET  /calendar/callback  -> Google redirects here; exchanges code for tokens + saves to DB
GET  /calendar/status    -> returns whether this user has connected their Google Calendar
DELETE /calendar/revoke  -> disconnects the user Google Calendar (deletes stored tokens)
"""

import hashlib
import hmac
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_token
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User as UserModel
from app.models.user_calendar_token import UserCalendarToken
from app.services.calendar import (
    build_authorization_url,
    decrypt_token,
    encrypt_token,
    exchange_code_for_tokens,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["calendar"])


# ---------------------------------------------------------------------------
# State token helpers (CSRF protection for the OAuth flow)
# ---------------------------------------------------------------------------

def _make_state(user_db_id: int) -> str:
    """Sign user_db_id with CALENDAR_STATE_SECRET to produce a tamper-proof state param."""
    msg = str(user_db_id).encode()
    sig = hmac.new(settings.CALENDAR_STATE_SECRET.encode(), msg, hashlib.sha256).hexdigest()
    return f"{user_db_id}.{sig}"


def _verify_state(state: str) -> int:
    """Verify the state param and return user_db_id, or raise HTTPException."""
    try:
        user_db_id_str, sig = state.split(".", 1)
        expected_sig = hmac.new(
            settings.CALENDAR_STATE_SECRET.encode(),
            user_db_id_str.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            raise ValueError("bad sig")
        return int(user_db_id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or tampered OAuth state parameter.")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _resolve_user(firebase_uid: str, db: AsyncSession) -> UserModel:
    result = await db.execute(
        select(UserModel).where(UserModel.firebase_uid == firebase_uid)
    )
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/auth")
async def calendar_auth(
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Step 1 of the OAuth flow.

    Returns a Google consent URL. The frontend should open this URL (in a
    browser tab or WebView). After the user grants access, Google redirects
    to /api/v1/calendar/callback automatically.
    """
    if not settings.GOOGLE_CALENDAR_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="Google Calendar integration is not configured on this server.",
        )
    user = await _resolve_user(token_data["uid"], db)
    state = _make_state(user.id)
    auth_url = build_authorization_url(state)
    logger.info("Calendar auth URL generated for user_id: %s", user.id)
    return {"auth_url": auth_url, "message": "Open this URL in a browser to connect your Google Calendar."}


@router.get("/callback")
async def calendar_callback(
    code: str = Query(..., description="One-time authorization code from Google"),
    state: str = Query(..., description="CSRF state token"),
    db: AsyncSession = Depends(get_db),
):
    """
    Step 2 of the OAuth flow — Google redirects here after user consent.

    Exchanges the one-time code for tokens, encrypts them, and saves to DB.
    Redirects the browser back to the frontend on success.
    """
    user_db_id = _verify_state(state)

    # Fetch the user
    result = await db.execute(select(UserModel).where(UserModel.id == user_db_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    # Exchange code for tokens (pass state so the PKCE verifier can be retrieved)
    try:
        token_data = exchange_code_for_tokens(code, state=state)
    except Exception as exc:
        logger.exception("Token exchange failed for user_id: %s", user_db_id)
        raise HTTPException(status_code=502, detail=f"Google token exchange failed: {exc}")

    if not token_data.get("refresh_token"):
        raise HTTPException(
            status_code=400,
            detail=(
                "Google did not return a refresh_token. "
                "This usually means the user has already granted access once. "
                "To fix: go to https://myaccount.google.com/permissions, revoke access "
                "to this app, then try connecting again."
            ),
        )

    # Encrypt tokens before storing
    enc_access = encrypt_token(token_data["access_token"])
    enc_refresh = encrypt_token(token_data["refresh_token"])

    # Upsert — update if already exists, create if not
    existing_result = await db.execute(
        select(UserCalendarToken).where(UserCalendarToken.user_id == user.id)
    )
    existing = existing_result.scalars().first()

    if existing:
        existing.encrypted_access_token = enc_access
        existing.encrypted_refresh_token = enc_refresh
        existing.token_expiry = token_data.get("expiry")
        existing.google_email = token_data.get("google_email")
        existing.updated_at = datetime.utcnow()
        logger.info("Calendar token updated for user_id: %s", user.id)
    else:
        new_token = UserCalendarToken(
            user_id=user.id,
            encrypted_access_token=enc_access,
            encrypted_refresh_token=enc_refresh,
            token_expiry=token_data.get("expiry"),
            google_email=token_data.get("google_email"),
        )
        db.add(new_token)
        logger.info("Calendar token created for user_id: %s", user.id)

    await db.commit()

    # Redirect browser back to frontend success page
    # Change this URL to your actual frontend success route
    return RedirectResponse(url="https://aura-health-frontend-five.vercel.app?calendar_connected=true")


@router.get("/status")
async def calendar_status(
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns whether the authenticated user has connected their Google Calendar.
    """
    user = await _resolve_user(token_data["uid"], db)
    result = await db.execute(
        select(UserCalendarToken).where(UserCalendarToken.user_id == user.id)
    )
    cal_token = result.scalars().first()
    if not cal_token:
        return {"connected": False, "google_email": None}
    return {
        "connected": True,
        "google_email": cal_token.google_email,
        "granted_at": cal_token.granted_at.isoformat(),
    }


@router.delete("/revoke", status_code=204)
async def calendar_revoke(
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Disconnects the user Google Calendar by deleting stored tokens.
    Also attempts to revoke the token at Google (best effort).
    """
    user = await _resolve_user(token_data["uid"], db)
    result = await db.execute(
        select(UserCalendarToken).where(UserCalendarToken.user_id == user.id)
    )
    cal_token = result.scalars().first()
    if not cal_token:
        return  # already disconnected — idempotent

    # Best-effort revoke at Google
    try:
        import httpx
        refresh = decrypt_token(cal_token.encrypted_refresh_token)
        httpx.post(
            "https://oauth2.googleapis.com/revoke",
            params={"token": refresh},
            headers={"content-type": "application/x-www-form-urlencoded"},
            timeout=5,
        )
    except Exception:
        logger.warning("Could not revoke token at Google for user_id: %s", user.id)

    await db.delete(cal_token)
    await db.commit()
    logger.info("Calendar disconnected for user_id: %s", user.id)
