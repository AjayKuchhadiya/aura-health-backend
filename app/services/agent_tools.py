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
from typing import Optional

from sqlalchemy.future import select

from app.core.database import AsyncSessionLocal
from app.models.doctor import Doctor as DoctorModel
from app.models.user import User as UserModel
from app.services.osm import search_nearby_healthcare

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Doctor search tools
# ---------------------------------------------------------------------------


async def search_doctors(
    specialty: str,
    is_available: bool = True,
) -> dict:
    """
    Search for doctors on the Aura platform by medical specialty.

    Use this tool when the user asks to find a doctor, book a consultation,
    or needs a recommendation for a specific type of specialist
    (e.g. cardiologist, dermatologist, general practitioner).

    Args:
        specialty: The medical specialty to search for, e.g. 'cardiologist',
                   'dermatologist', 'general practitioner', 'pediatrician'.
        is_available: If True (default) only return doctors currently marked
                      as available for consultations.

    Returns:
        A dict with a 'doctors' list. Each entry contains the doctor's id,
        name, specialization, years_of_experience, consultation_fee,
        languages, rating, and bio.
    """
    logger.info(
        "Tool: search_doctors — specialty='%s', is_available=%s",
        specialty,
        is_available,
    )
    try:
        async with AsyncSessionLocal() as db:
            stmt = (
                select(DoctorModel, UserModel)
                .join(UserModel, DoctorModel.user_id == UserModel.id)
                .where(
                    DoctorModel.specialization.ilike(f"%{specialty}%"),
                )
            )
            if is_available:
                stmt = stmt.where(DoctorModel.is_available.is_(True))

            result = await db.execute(stmt)
            rows = result.all()

        if not rows:
            return {
                "doctors": [],
                "message": f"No {'available ' if is_available else ''}doctors found for specialty '{specialty}'. "
                "Try a broader term (e.g. 'general practitioner') or set is_available=False.",
            }

        doctors = []
        for doctor, user in rows:
            doctors.append(
                {
                    "id": doctor.id,
                    "name": user.username or "Unknown",
                    "specialization": doctor.specialization,
                    "years_of_experience": doctor.years_of_experience,
                    "consultation_fee": doctor.consultation_fee,
                    "languages": doctor.languages or [],
                    "rating": doctor.rating,
                    "bio": doctor.bio or "",
                    "is_available": doctor.is_available,
                    "is_verified": doctor.is_verified,
                    # Location context — lets the agent say "Dr. X is based in your city"
                    "city": doctor.city,
                    "state": doctor.state,
                    "country": doctor.country,
                    "consultation_type": "online",
                }
            )

        return {"doctors": doctors, "total": len(doctors)}

    except Exception as exc:
        logger.exception("search_doctors failed")
        return {"error": f"Failed to search doctors: {exc}"}


async def get_doctor_details(doctor_id: int) -> dict:
    """
    Retrieve full profile details for a specific doctor by their numeric ID.

    Use this tool when the user asks for more information about a particular
    doctor after a search, or wants to see the doctor's education, certifications,
    availability schedule, or contact details before booking.

    Args:
        doctor_id: The numeric ID of the doctor (obtained from search_doctors).

    Returns:
        A dict containing the doctor's full profile including specialization,
        education, certifications, availability, consultation_fee, and
        contact/language info. Returns an 'error' key if not found.
    """
    logger.info("Tool: get_doctor_details — doctor_id=%s", doctor_id)
    try:
        async with AsyncSessionLocal() as db:
            stmt = (
                select(DoctorModel, UserModel)
                .join(UserModel, DoctorModel.user_id == UserModel.id)
                .where(DoctorModel.id == doctor_id)
            )
            result = await db.execute(stmt)
            row = result.first()

        if not row:
            return {"error": f"Doctor with ID {doctor_id} not found."}

        doctor, user = row
        return {
            "id": doctor.id,
            "name": user.username or "Unknown",
            "email": user.email,
            "specialization": doctor.specialization,
            "license_number": doctor.license_number,
            "years_of_experience": doctor.years_of_experience,
            "education": doctor.education or [],
            "certifications": doctor.certifications or [],
            "languages": doctor.languages or [],
            "bio": doctor.bio or "",
            "consultation_fee": doctor.consultation_fee,
            "availability": doctor.availability or {},
            "rating": doctor.rating,
            "total_consultations": doctor.total_consultations,
            "is_verified": doctor.is_verified,
            "is_available": doctor.is_available,
        }

    except Exception as exc:
        logger.exception("get_doctor_details failed")
        return {"error": f"Failed to retrieve doctor details: {exc}"}


async def search_nearby_doctors(
    latitude: float,
    longitude: float,
    specialty: str = "",
    radius_km: float = 10.0,
) -> dict:
    """
    Search for in-person doctors, clinics, and hospitals near the user's
    current GPS location using OpenStreetMap data.

    Use this tool when the user wants to physically visit a doctor or needs
    to find a nearby clinic or hospital.  Always call this alongside
    search_doctors() so the user gets both in-person and online options.

    If no results are found within the given radius, the OSM layer will
    automatically retry with a 1.5× larger radius before returning empty.

    Args:
        latitude:   User's current latitude in decimal degrees.
        longitude:  User's current longitude in decimal degrees.
        specialty:  Optional medical specialty to hint at (e.g. 'cardiologist',
                    'dentist', 'dermatologist').  Used to contextualise the
                    results — OSM data may not always carry specialty tags.
        radius_km:  Search radius in kilometres (default 10 km, max sensible
                    value is 20 km for urban areas).

    Returns:
        A dict with a 'facilities' list. Each entry contains name, type,
        address, phone, website, opening_hours, distance_km, and
        booking_contact (phone → website → address fallback chain).
        Returns an 'error' key on failure.
    """
    logger.info(
        "Tool: search_nearby_doctors — lat=%s, lon=%s, specialty='%s', radius=%skm",
        latitude,
        longitude,
        specialty,
        radius_km,
    )
    try:
        radius_m = int(min(radius_km, 20) * 1000)  # cap at 20 km
        facilities = await search_nearby_healthcare(
            latitude=latitude,
            longitude=longitude,
            radius_m=radius_m,
            limit=8,
            specialty=specialty,
        )

        if not facilities:
            return {
                "facilities": [],
                "message": (
                    f"No healthcare facilities found within {radius_km} km of your location "
                    "on OpenStreetMap. Try increasing the radius or search by address."
                ),
            }

        # Surface specialty hint to help the agent contextualise results
        specialty_note = (
            f"Results are all healthcare facilities within {radius_km} km. "
            f"Filter or highlight those relevant to '{specialty}' based on their type/specialty tags."
            if specialty
            else f"All healthcare facilities within {radius_km} km of your location."
        )

        return {
            "facilities": facilities,
            "total": len(facilities),
            "note": specialty_note,
        }

    except Exception as exc:
        logger.exception("search_nearby_doctors tool failed")
        return {"error": f"Failed to search nearby doctors: {exc}"}


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
                     Example: {"date": "2024-01-15", "symptoms": ["headache"],
                               "mood": "tired", "weight_kg": 72.5}

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
# Public list of all tools to register with the agent
# ---------------------------------------------------------------------------

AGENT_TOOLS = [
    search_doctors,
    search_nearby_doctors,
    get_doctor_details,
    log_health_update,
]
