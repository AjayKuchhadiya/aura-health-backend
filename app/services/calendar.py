"""
Google Calendar service — per-user OAuth token management and event operations.

Architecture:
  - Tokens are encrypted with Fernet (symmetric encryption derived from SECRET_KEY)
    before being written to the database, so raw tokens never appear in DB dumps.
  - The refresh_token never expires (unless revoked). We use it to silently obtain
    a fresh access_token before every Calendar API call.
  - The frontend sends the user to GET /api/v1/calendar/auth, which returns a
    Google consent URL. After the user consents, Google POSTs the one-time code
    to GET /api/v1/calendar/callback. We exchange it for tokens here.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

from cryptography.fernet import Fernet
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Encryption helpers (Fernet symmetric, key derived from SECRET_KEY)
# ---------------------------------------------------------------------------

def _get_fernet() -> Fernet:
    """Derive a 32-byte Fernet key from the app SECRET_KEY."""
    raw = settings.SECRET_KEY.encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
    return Fernet(key)


def encrypt_token(token: str) -> str:
    return _get_fernet().encrypt(token.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    return _get_fernet().decrypt(encrypted.encode()).decode()


# ---------------------------------------------------------------------------
# OAuth flow helpers
# ---------------------------------------------------------------------------

_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def _build_flow(state: Optional[str] = None) -> Flow:
    """Build a google-auth-oauthlib Flow from env-var credentials."""
    if not settings.GOOGLE_CALENDAR_CLIENT_ID or not settings.GOOGLE_CALENDAR_CLIENT_SECRET:
        raise RuntimeError(
            "GOOGLE_CALENDAR_CLIENT_ID and GOOGLE_CALENDAR_CLIENT_SECRET must be set."
        )
    client_config = {
        "web": {
            "client_id": settings.GOOGLE_CALENDAR_CLIENT_ID,
            "client_secret": settings.GOOGLE_CALENDAR_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.GOOGLE_CALENDAR_REDIRECT_URI],
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=_SCOPES,
        state=state,
    )
    flow.redirect_uri = settings.GOOGLE_CALENDAR_REDIRECT_URI
    return flow


def build_authorization_url(state: str) -> str:
    """
    Return the Google consent URL the user must visit.
    access_type=offline ensures we get a refresh_token.
    prompt=consent forces Google to always return the refresh_token
    (important for returning users — without this, Google only sends it once).
    """
    flow = _build_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=state,
        include_granted_scopes="true",
    )
    return auth_url


def exchange_code_for_tokens(code: str) -> dict:
    """
    Exchange the one-time authorization code for access + refresh tokens.
    Returns a dict with access_token, refresh_token, expiry, and email.
    """
    flow = _build_flow()
    flow.fetch_token(code=code)
    creds: Credentials = flow.credentials

    # Fetch the user's Google email via the userinfo endpoint
    google_email = None
    try:
        import httpx
        resp = httpx.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            google_email = resp.json().get("email")
    except Exception:
        logger.warning("Could not fetch Google userinfo email")

    return {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "expiry": creds.expiry,       # datetime or None
        "google_email": google_email,
    }


# ---------------------------------------------------------------------------
# Credentials factory — auto-refreshes when expired
# ---------------------------------------------------------------------------

def _build_credentials(access_token: str, refresh_token: str, expiry: Optional[datetime]) -> Credentials:
    """Build a google.oauth2.credentials.Credentials that auto-refreshes."""
    return Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CALENDAR_CLIENT_ID,
        client_secret=settings.GOOGLE_CALENDAR_CLIENT_SECRET,
        scopes=_SCOPES,
        expiry=expiry,
    )


# ---------------------------------------------------------------------------
# Calendar API operations
# ---------------------------------------------------------------------------

_FREQUENCY_TO_RRULE = {
    "once daily": "RRULE:FREQ=DAILY",
    "daily": "RRULE:FREQ=DAILY",
    "twice daily": "RRULE:FREQ=DAILY",   # handled separately — creates 2 events
    "every 8 hours": "RRULE:FREQ=DAILY;INTERVAL=1",
    "weekly": "RRULE:FREQ=WEEKLY",
    "monthly": "RRULE:FREQ=MONTHLY",
}


async def create_medication_reminder(
    access_token: str,
    refresh_token: str,
    token_expiry: Optional[datetime],
    medication_name: str,
    dosage: str,
    frequency: str,
    start_date: str,        # ISO 8601 date string e.g. "2026-06-14"
    start_time: str = "08:00",  # local time HH:MM
    timezone: str = "UTC",
) -> list[str]:
    """
    Create recurring Google Calendar reminder events for a medication.

    For "twice daily", creates two events: one at start_time, one 12 hours later.
    Returns a list of created event IDs.
    """
    import asyncio

    creds = _build_credentials(access_token, refresh_token, token_expiry)

    def _create() -> list[str]:
        service = build("calendar", "v3", credentials=creds)
        event_ids = []

        base_event = {
            "summary": f"💊 Take {medication_name} {dosage}",
            "description": f"Medication reminder: {medication_name} {dosage}\nFrequency: {frequency}",
            "start": {
                "dateTime": f"{start_date}T{start_time}:00",
                "timeZone": timezone,
            },
            "end": {
                "dateTime": f"{start_date}T{start_time}:10",  # 10-min block
                "timeZone": timezone,
            },
            "reminders": {
                "useDefault": False,
                "overrides": [{"method": "popup", "minutes": 10}],
            },
        }

        rrule = _FREQUENCY_TO_RRULE.get(frequency.lower(), "RRULE:FREQ=DAILY")

        if frequency.lower() == "twice daily":
            # Morning event
            morning = dict(base_event)
            morning["recurrence"] = [rrule]
            e1 = service.events().insert(calendarId="primary", body=morning).execute()
            event_ids.append(e1["id"])

            # Evening event (12 hours later)
            h, m = map(int, start_time.split(":"))
            evening_h = (h + 12) % 24
            evening_time = f"{evening_h:02d}:{m:02d}"
            evening = dict(base_event)
            evening["summary"] = f"💊 Take {medication_name} {dosage} (evening)"
            evening["start"] = {"dateTime": f"{start_date}T{evening_time}:00", "timeZone": timezone}
            evening["end"]   = {"dateTime": f"{start_date}T{evening_time}:10", "timeZone": timezone}
            evening["recurrence"] = [rrule]
            e2 = service.events().insert(calendarId="primary", body=evening).execute()
            event_ids.append(e2["id"])
        else:
            base_event["recurrence"] = [rrule]
            created = service.events().insert(calendarId="primary", body=base_event).execute()
            event_ids.append(created["id"])

        return event_ids

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _create)


async def delete_calendar_event(
    access_token: str,
    refresh_token: str,
    token_expiry: Optional[datetime],
    event_id: str,
) -> bool:
    """Delete a Google Calendar event by ID. Returns True on success."""
    import asyncio

    creds = _build_credentials(access_token, refresh_token, token_expiry)

    def _delete():
        service = build("calendar", "v3", credentials=creds)
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        return True

    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _delete)
    except Exception as exc:
        logger.error("Failed to delete calendar event %s: %s", event_id, exc)
        return False
