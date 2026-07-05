"""
Agent tool functions for the Aura Health AI Navigator.

Each function in this module is registered as a callable tool that the
LlmAgent can invoke via Gemini's Function Calling API.  Google ADK reads
the function signature (type annotations) and docstring to auto-generate
the JSON schema that is sent to the model.

Rules for every tool function:
- Must be an async def with full type annotations on all parameters.
- Must return a plain dict (JSON-serialisable).
- Must have a clear docstring — ADK surfaces this to the model as the tool
  description, so be explicit about what the tool does and when to use it.
- Never raise exceptions to the caller; return {"error": "..."} instead so
  the agent can relay a helpful message to the user.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.future import select

from app.core.database import AsyncSessionLocal
from app.models.medication import Medication as MedicationModel
from app.models.user import User as UserModel
from app.models.user_calendar_token import UserCalendarToken

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Health diary tool
# ---------------------------------------------------------------------------


async def log_health_update(user_db_id: int, update_data: dict) -> dict:
    """
    Log a health update into the user's Digital Twin profile in the database.

    Call this tool whenever the user wants to record daily health data during
    a conversation — for example: symptoms, mood, weight, blood pressure
    readings, sleep quality, or any personal health note.

    Args:
        user_db_id:  The user's integer database ID (available in your session
                     state as {user_db_id}).
        update_data: A dict of health data to merge into the 'daily_logs' list
                     inside the user's medical_profile.  Include a 'date' key
                     (ISO 8601) and any relevant fields the user mentioned.
                     Use this schema (only include keys that were actually discussed):
                     {
                       "date": "<today's ISO 8601 date>",
                       "type": "symptom|vitals|mood|general",
                       "symptoms": ["symptom1", "symptom2"],
                       "severity": 7,
                       "duration": "since this morning",
                       "triggers": ["skipped lunch", "stress"],
                       "mood": "anxious",
                       "medication_taken": "ibuprofen 400mg",
                       "notes": "any other context the user mentioned"
                     }

    Returns:
        {"success": True} on success, or {"error": "..."} on failure.
    """
    logger.info("Tool: log_health_update — user_db_id=%s", user_db_id)
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(UserModel).where(UserModel.id == user_db_id)
            )
            user = result.scalars().first()
            if not user:
                return {"error": f"User {user_db_id} not found."}

            profile = dict(user.medical_profile or {})
            daily_logs = profile.setdefault("daily_logs", [])
            daily_logs.append(update_data)
            user.medical_profile = profile
            await db.commit()
        return {"success": True, "message": "Health update logged to your Digital Twin profile."}
    except Exception as exc:
        logger.exception("log_health_update failed")
        return {"error": f"Failed to log health update: {exc}"}


# ---------------------------------------------------------------------------
# Google Calendar tool
# ---------------------------------------------------------------------------


async def create_calendar_event(
    user_db_id: int,
    medication_name: str,
    dosage: str,
    frequency: str,
    start_date: str,
    start_time: str = "08:00",
    timezone: str = "UTC",
) -> dict:
    """
    Create recurring Google Calendar reminder events for a medication.

    Call this tool when the user asks to schedule a medication reminder on
    their Google Calendar after adding a new medication.

    Args:
        user_db_id:       The user's integer database ID ({user_db_id} from session state).
        medication_name:  Name of the medication, e.g. "Metformin".
        dosage:           Dosage string, e.g. "500mg".
        frequency:        How often to take it. Supported values: "once daily",
                          "twice daily", "weekly", "monthly".
        start_date:       ISO 8601 date when reminders should start, e.g. "2026-06-14".
        start_time:       Time of first reminder in HH:MM format (24-hour), e.g. "08:00".
        timezone:         IANA timezone name, e.g. "America/New_York". Defaults to UTC.

    Returns:
        {"event_ids": [...], "success": True} on success, or {"error": "..."} on failure.
        Store the returned event_ids on the medication record so the events can be
        updated or deleted later.
    """
    logger.info(
        "Tool: create_calendar_event — user_db_id=%s, med=%s, freq=%s",
        user_db_id, medication_name, frequency,
    )
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(UserCalendarToken).where(UserCalendarToken.user_id == user_db_id)
            )
            cal_token = result.scalars().first()

        if not cal_token:
            return {
                "error": (
                    "This user has not connected their Google Calendar yet. "
                    "Ask them to visit GET /api/v1/calendar/auth to connect it first."
                )
            }

        from app.services.calendar import create_medication_reminder, decrypt_token

        access_token = decrypt_token(cal_token.encrypted_access_token)
        refresh_token = decrypt_token(cal_token.encrypted_refresh_token)

        event_ids = await create_medication_reminder(
            access_token=access_token,
            refresh_token=refresh_token,
            token_expiry=cal_token.token_expiry,
            medication_name=medication_name,
            dosage=dosage,
            frequency=frequency,
            start_date=start_date,
            start_time=start_time,
            timezone=timezone,
        )

        logger.info(
            "Calendar events created — user_db_id=%s, event_ids=%s", user_db_id, event_ids
        )
        return {
            "success": True,
            "event_ids": event_ids,
            "message": (
                f"Created {len(event_ids)} recurring reminder(s) on Google Calendar for "
                f"{medication_name} {dosage}. Store the event_ids on the medication record."
            ),
        }

    except Exception as exc:
        logger.exception("create_calendar_event failed")
        return {"error": f"Failed to create calendar event: {exc}"}


# ---------------------------------------------------------------------------
# Active medications tool
# ---------------------------------------------------------------------------


async def get_active_medications(user_db_id: int) -> dict:
    """
    Retrieve the patient's current active medications from the database.

    Call this tool proactively whenever the user asks about their medications,
    wants to check dosages or schedules, discusses adherence, asks about drug
    interactions, or when scheduling a new medication reminder.

    Args:
        user_db_id: The user's integer database ID ({user_db_id} from session state).

    Returns:
        {"medications": [...], "count": N} on success, or {"error": "..."} on failure.
        Each entry includes: id, medication_name, dosage, frequency, reminder_time,
        start_date, end_date, notes.
    """
    logger.info("Tool: get_active_medications — user_db_id=%s", user_db_id)
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(MedicationModel)
                .where(
                    MedicationModel.user_id == user_db_id,
                    or_(
                        MedicationModel.end_date.is_(None),
                        MedicationModel.end_date >= date.today(),
                    ),
                )
                .order_by(MedicationModel.start_date.desc())
            )
            medications = result.scalars().all()
            med_list = [
                {
                    "id": m.id,
                    "medication_name": m.medication_name,
                    "dosage": m.dosage,
                    "frequency": m.frequency,
                    "reminder_time": m.reminder_time,
                    "start_date": str(m.start_date) if m.start_date else None,
                    "end_date": str(m.end_date) if m.end_date else None,
                    "notes": m.notes,
                }
                for m in medications
            ]
        return {"medications": med_list, "count": len(med_list)}
    except Exception as exc:
        logger.exception("get_active_medications failed")
        return {"error": f"Failed to fetch medications: {exc}"}


# ---------------------------------------------------------------------------
# Health diary retrieval tool
# ---------------------------------------------------------------------------


async def get_health_diary(user_db_id: int, limit: int = 10) -> dict:
    """
    Retrieve recent health diary entries from the patient's Digital Twin profile.

    Call this tool when the user asks about past symptoms, health trends,
    recurring patterns, or when preparing structured questions for a doctor's
    appointment. Increase limit to 20–30 for deeper longitudinal analysis.

    Args:
        user_db_id: The user's integer database ID ({user_db_id} from session state).
        limit:      Maximum number of recent entries to return (default 10, max 30).

    Returns:
        {"entries": [...], "count": N, "total": M} on success, most-recent first.
        Returns {"error": "..."} on failure.
    """
    logger.info("Tool: get_health_diary — user_db_id=%s, limit=%s", user_db_id, limit)
    try:
        limit = min(int(limit), 30)  # hard cap to avoid context overflow
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(UserModel).where(UserModel.id == user_db_id)
            )
            user = result.scalars().first()
            if not user:
                return {"error": f"User {user_db_id} not found."}
            all_logs = list((user.medical_profile or {}).get("daily_logs", []))

        recent_logs = list(reversed(all_logs[-limit:]))
        return {
            "entries": recent_logs,
            "count": len(recent_logs),
            "total": len(all_logs),
        }
    except Exception as exc:
        logger.exception("get_health_diary failed")
        return {"error": f"Failed to fetch health diary: {exc}"}


# ---------------------------------------------------------------------------
# Public list of all tools to register with the agent
# ---------------------------------------------------------------------------

AGENT_TOOLS = [
    get_active_medications,
    get_health_diary,
    log_health_update,
    create_calendar_event,
]
