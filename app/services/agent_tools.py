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
from app.services.ambulance import AmbulanceSearchService

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


# ---------------------------------------------------------------------------
# Ambulance tools
# ---------------------------------------------------------------------------


async def find_nearest_ambulance(latitude: float, longitude: float) -> dict:
    """
    Locate the nearest available ambulance given the user's GPS coordinates.

    Use this tool only when the user is experiencing or witnessing a medical
    emergency and has shared their location coordinates.  Always remind the
    user to also call local emergency services (e.g. 911).

    Args:
        latitude:  User's current latitude in decimal degrees (e.g. 37.7749).
        longitude: User's current longitude in decimal degrees (e.g. -122.4194).

    Returns:
        A dict with 'ambulance' details including estimated_arrival_minutes,
        unit_id, driver_name, and contact_number. Returns an 'error' key on
        failure.
    """
    logger.info("Tool: find_nearest_ambulance — lat=%s, lon=%s", latitude, longitude)
    try:
        result = await AmbulanceSearchService.find_nearest_ambulance(
            latitude, longitude
        )
        if result is None:
            return {
                "error": "No ambulances are currently available in your area. "
                "Please call emergency services immediately (911 or local equivalent)."
            }
        return result

    except Exception as exc:
        logger.exception("find_nearest_ambulance tool failed")
        return {
            "error": f"Could not locate an ambulance: {exc}. "
            "Please call emergency services immediately."
        }


async def request_ambulance(location_description: str) -> dict:
    """
    Request an ambulance dispatch to a described location (street address or landmark).

    Use this tool when the user does not have GPS coordinates but can describe
    their location in words (e.g. '123 Main Street, Apt 4B' or 'Central Park
    near the fountain').  Only invoke this during a confirmed or suspected
    medical emergency.

    Args:
        location_description: A plain-language description of the pickup location,
                               such as a full street address or a nearby landmark.

    Returns:
        A dict with dispatch confirmation details including a 'request_id',
        'status', and 'estimated_arrival_minutes'. Returns an 'error' key on
        failure.
    """
    logger.info("Tool: request_ambulance — location='%s'", location_description)
    try:
        result = await AmbulanceSearchService.search_by_location(location_description)
        if result is None:
            return {
                "error": "Unable to dispatch an ambulance to that location. "
                "Please call emergency services (911 or local equivalent) immediately."
            }
        return {
            "status": "dispatched",
            "location": location_description,
            "details": result,
        }

    except Exception as exc:
        logger.exception("request_ambulance tool failed")
        return {
            "error": f"Ambulance request failed: {exc}. "
            "Please call emergency services immediately."
        }


# ---------------------------------------------------------------------------
# Emergency triage tool
# ---------------------------------------------------------------------------


async def assess_emergency_level(symptoms: str) -> dict:
    """
    Assess the urgency level of reported symptoms and return a recommended
    triage action without providing a medical diagnosis.

    Use this tool when the user describes symptoms and you need to decide
    whether to recommend: (1) calling emergency services immediately,
    (2) visiting an emergency room, (3) booking a same-day doctor appointment,
    or (4) general self-care advice.

    Args:
        symptoms: A plain-language description of the symptoms or situation
                  provided by the user, e.g. 'severe chest pain radiating to
                  left arm' or 'mild headache for two days'.

    Returns:
        A dict with:
          - 'urgency_level': one of 'critical', 'urgent', 'moderate', 'low'
          - 'recommended_action': what the user should do next
          - 'call_emergency': bool — True if 911/emergency services must be called
          - 'disclaimer': the standard AI health navigator disclaimer
    """
    logger.info("Tool: assess_emergency_level — symptoms='%s'", symptoms)

    symptoms_lower = symptoms.lower()

    # Critical life-threatening keyword matching
    critical_keywords = [
        "chest pain",
        "heart attack",
        "can't breathe",
        "cannot breathe",
        "difficulty breathing",
        "shortness of breath",
        "unconscious",
        "unresponsive",
        "stroke",
        "paralysis",
        "severe bleeding",
        "overdose",
        "poisoning",
        "loss of consciousness",
        "seizure",
        "anaphylaxis",
        "allergic reaction",
        "choking",
    ]

    urgent_keywords = [
        "high fever",
        "broken bone",
        "fracture",
        "deep cut",
        "head injury",
        "vomiting blood",
        "blood in urine",
        "severe abdominal pain",
        "can't walk",
        "fainting",
        "dizziness",
        "blurred vision",
    ]

    is_critical = any(kw in symptoms_lower for kw in critical_keywords)
    is_urgent = any(kw in symptoms_lower for kw in urgent_keywords)

    disclaimer = (
        "⚠️ Disclaimer: I am an AI Health Navigator, not a licensed medical professional. "
        "This information is not a diagnosis. Please consult a qualified healthcare provider "
        "for medical advice."
    )

    if is_critical:
        return {
            "urgency_level": "critical",
            "recommended_action": (
                "CALL EMERGENCY SERVICES (911 or your local equivalent) IMMEDIATELY. "
                "Do not wait. I can also dispatch an ambulance through the Aura platform "
                "if you share your location."
            ),
            "call_emergency": True,
            "disclaimer": disclaimer,
        }
    elif is_urgent:
        return {
            "urgency_level": "urgent",
            "recommended_action": (
                "Go to the nearest emergency room or urgent care centre. "
                "If you cannot travel safely, call emergency services. "
                "I can help you find an available doctor on Aura if needed."
            ),
            "call_emergency": False,
            "disclaimer": disclaimer,
        }
    else:
        return {
            "urgency_level": "low",
            "recommended_action": (
                "Monitor your symptoms. Consider booking a consultation with a doctor "
                "on the Aura platform. If symptoms worsen, seek immediate care."
            ),
            "call_emergency": False,
            "disclaimer": disclaimer,
        }


# ---------------------------------------------------------------------------
# Public list of all tools to register with the agent
# ---------------------------------------------------------------------------

AGENT_TOOLS = [
    search_doctors,
    get_doctor_details,
    find_nearest_ambulance,
    request_ambulance,
    assess_emergency_level,
]
