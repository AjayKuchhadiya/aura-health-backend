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

# Module-level store for Flow objects keyed by OAuth state.
# The same Flow instance must be used for both authorization_url() and
# fetch_token() so its internal PKCE code_verifier survives across the
# two HTTP requests (GET /auth → GET /callback).
# Entries are consumed (popped) in exchange_code_for_tokens.
_pending_flows: dict = {}


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
    The Flow object is stored by state so the same instance (including its
    internal PKCE code_verifier) is reused during token exchange.
    """
    flow = _build_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=state,
        include_granted_scopes="true",
    )
    # Persist the flow so fetch_token() can reuse the same PKCE verifier
    _pending_flows[state] = flow
    return auth_url


def exchange_code_for_tokens(code: str, state: str = "") -> dict:
    """
    Exchange the one-time authorization code for access + refresh tokens.
    Reuses the Flow object stored during build_authorization_url so that
    any PKCE code_verifier is automatically included in the token request.
    Returns a dict with access_token, refresh_token, expiry, and email.
    """
    # Retrieve and consume the stored flow (falls back to a fresh one)
    flow = _pending_flows.pop(state, None) if state else None
    if flow is None:
        flow = _build_flow(state=state or None)
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

import re as _re


def _parse_frequency(frequency: str) -> tuple[str, int]:
    """
    Parse a free-text medication frequency string into an RRULE and a
    doses-per-day count. The doses count drives how many calendar events
    are created (one per dose, spaced evenly through the day).

    Returns: (rrule_string, doses_per_day)

    Examples:
        "once daily"         → ("RRULE:FREQ=DAILY", 1)
        "twice daily"        → ("RRULE:FREQ=DAILY", 2)
        "three times daily"  → ("RRULE:FREQ=DAILY", 3)
        "every 8 hours"      → ("RRULE:FREQ=DAILY", 3)
        "every 3 days"       → ("RRULE:FREQ=DAILY;INTERVAL=3", 1)
        "every 2 weeks"      → ("RRULE:FREQ=WEEKLY;INTERVAL=2", 1)
        "alternate days"     → ("RRULE:FREQ=DAILY;INTERVAL=2", 1)
        "weekly"             → ("RRULE:FREQ=WEEKLY", 1)
        "monthly"            → ("RRULE:FREQ=MONTHLY", 1)
    """
    f = frequency.lower().strip()

    # ── doses per day from explicit count ───────────────────────────────────
    _word_to_num = {"once": 1, "one": 1, "twice": 2, "two": 2,
                    "three": 3, "thrice": 3, "four": 4, "five": 5, "six": 6}

    # "N times daily/a day" or "Nx daily"
    m = _re.search(r'(\d+)\s*(?:times?|x)\s*(?:a\s*day|daily|per\s*day)', f)
    if m:
        return "RRULE:FREQ=DAILY", int(m.group(1))

    # "twice daily" / "three times daily"
    for word, n in _word_to_num.items():
        if _re.search(rf'\b{word}\b', f) and _re.search(r'\b(daily|a\s*day|per\s*day)\b', f):
            return "RRULE:FREQ=DAILY", n

    # BID / TID / QID (Latin pharmacy shorthand)
    if _re.search(r'\bbid\b', f): return "RRULE:FREQ=DAILY", 2
    if _re.search(r'\btid\b', f): return "RRULE:FREQ=DAILY", 3
    if _re.search(r'\bqid\b', f): return "RRULE:FREQ=DAILY", 4

    # "every N hours" → doses = 24/N
    m = _re.search(r'every\s+(\d+)\s*hours?', f)
    if m:
        hours = int(m.group(1))
        doses = max(1, round(24 / hours))
        return "RRULE:FREQ=DAILY", doses

    # ── interval-based (not daily) ───────────────────────────────────────────
    # "every N days"
    m = _re.search(r'every\s+(\d+)\s*days?', f)
    if m:
        return f"RRULE:FREQ=DAILY;INTERVAL={m.group(1)}", 1

    # "alternate days" / "every other day"
    if _re.search(r'\b(alternate|alternating|every\s+other)\b', f):
        return "RRULE:FREQ=DAILY;INTERVAL=2", 1

    # "every N weeks"
    m = _re.search(r'every\s+(\d+)\s*weeks?', f)
    if m:
        return f"RRULE:FREQ=WEEKLY;INTERVAL={m.group(1)}", 1

    if _re.search(r'\bweekly\b', f):  return "RRULE:FREQ=WEEKLY", 1
    if _re.search(r'\bmonthly\b', f): return "RRULE:FREQ=MONTHLY", 1

    # Default: once daily
    return "RRULE:FREQ=DAILY", 1


def _add_hours(time_str: str, hours: float) -> str:
    """Add hours to an HH:MM string, wrapping at 24h."""
    h, m = map(int, time_str.split(":"))
    total_minutes = h * 60 + m + int(hours * 60)
    total_minutes %= 24 * 60
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


async def create_medication_reminder(
    access_token: str,
    refresh_token: str,
    token_expiry: Optional[datetime],
    medication_name: str,
    dosage: str,
    frequency: str,
    start_date: str,        # ISO 8601 date string e.g. "2026-06-14"
    start_time: str = "08:00",  # local time HH:MM — first dose
    timezone: str = "UTC",
) -> list[str]:
    """
    Create recurring Google Calendar reminder events for a medication.

    Automatically creates one event per daily dose, evenly spaced from
    start_time. E.g. "three times daily" starting at 08:00 → 08:00, 16:00, 00:00.
    Returns a list of created event IDs.
    """
    import asyncio

    rrule, doses_per_day = _parse_frequency(frequency)
    interval_hours = 24 / doses_per_day

    # Build list of (time, label_suffix) for each dose
    dose_times: list[tuple[str, str]] = []
    suffixes = ["", " (2nd dose)", " (3rd dose)", " (4th dose)", " (5th dose)", " (6th dose)"]
    for i in range(doses_per_day):
        t = _add_hours(start_time, interval_hours * i)
        suffix = suffixes[i] if i < len(suffixes) else f" (dose {i+1})"
        dose_times.append((t, suffix))

    creds = _build_credentials(access_token, refresh_token, token_expiry)

    def _create() -> list[str]:
        service = build("calendar", "v3", credentials=creds)
        event_ids = []

        for dose_time, suffix in dose_times:
            event = {
                "summary": f"💊 Take {medication_name} {dosage}{suffix}",
                "description": (
                    f"Medication reminder: {medication_name} {dosage}\n"
                    f"Frequency: {frequency}"
                ),
                "start": {"dateTime": f"{start_date}T{dose_time}:00", "timeZone": timezone},
                "end":   {"dateTime": f"{start_date}T{dose_time}:10", "timeZone": timezone},
                "recurrence": [rrule],
                "reminders": {
                    "useDefault": False,
                    "overrides": [{"method": "popup", "minutes": 10}],
                },
            }
            created = service.events().insert(calendarId="primary", body=event).execute()
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
