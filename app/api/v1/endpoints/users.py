import copy
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm.attributes import flag_modified
from typing import List, Optional

from app.core.database import get_db
from app.api.deps import get_current_user_token
from app.models.lab_result import LabResult as LabResultModel
from app.models.medication import Medication as MedicationModel
from app.models.user import User as UserModel
from app.models.doctor import Doctor as DoctorModel
from app.schemas.patient import PatientOnboarding, PatientProfileResponse
from app.schemas.doctor import DoctorOnboarding, DoctorProfileResponse
from app.services.fhir_export import build_fhir_bundle

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/users",
    tags=["users"],
)


@router.post("/patient-profile", response_model=PatientProfileResponse)
async def onboard_patient(
    onboarding_data: PatientOnboarding,
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Create/Update Patient Profile
    """
    firebase_uid = token_data.get("uid")
    logger.info("Patient profile onboarding — uid: %s", firebase_uid)

    result = await db.execute(
        select(UserModel).where(UserModel.firebase_uid == firebase_uid)
    )
    user = result.scalars().first()

    if not user:
        logger.warning(
            "Patient onboarding failed — user not found for uid: %s", firebase_uid
        )
        raise HTTPException(status_code=404, detail="User not found")

    # Store the entire payload in the JSONB column
    user.medical_profile = onboarding_data.model_dump()
    user.role = "patient"

    await db.commit()
    await db.refresh(user)
    logger.info("Patient profile saved — user_id: %s", user.id)

    # Return wrapped response matching the contract
    return {"message": "Patient profile created successfully", "data": user}


@router.post("/doctor-profile", response_model=DoctorProfileResponse)
async def onboard_doctor(
    onboarding_data: DoctorOnboarding,
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Create/Update Doctor Profile
    """
    firebase_uid = token_data.get("uid")
    logger.info("Doctor profile onboarding — uid: %s", firebase_uid)

    result = await db.execute(
        select(UserModel).where(UserModel.firebase_uid == firebase_uid)
    )
    user = result.scalars().first()

    if not user:
        logger.warning(
            "Doctor onboarding failed — user not found for uid: %s", firebase_uid
        )
        raise HTTPException(status_code=404, detail="User not found")

    doc_result = await db.execute(
        select(DoctorModel).where(DoctorModel.user_id == user.id)
    )
    existing_doctor = doc_result.scalars().first()

    if existing_doctor:
        logger.warning(
            "Doctor onboarding failed — profile already exists for user_id: %s", user.id
        )
        raise HTTPException(
            status_code=400, detail="Doctor profile already exists for this user"
        )

    user.role = "doctor"
    if onboarding_data.name:
        user.username = onboarding_data.name

    education_dicts = [edu.model_dump() for edu in onboarding_data.education]

    new_doctor = DoctorModel(
        user_id=user.id,
        specialization=onboarding_data.specialization,
        license_number=onboarding_data.license_number,
        years_of_experience=onboarding_data.years_of_experience,
        education=education_dicts,
        certifications=onboarding_data.certifications,
        languages=onboarding_data.languages,
        bio=onboarding_data.bio,
        consultation_fee=onboarding_data.consultation_fee,
        availability=onboarding_data.availability,
    )

    db.add(new_doctor)
    await db.commit()
    await db.refresh(new_doctor)
    logger.info(
        "Doctor profile created — doctor_id: %s, user_id: %s", new_doctor.id, user.id
    )

    # Return wrapped response matching the contract
    return {"message": "Doctor profile created successfully", "data": new_doctor}


@router.get("/export/fhir")
async def export_fhir(
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Export the user's complete Digital Twin as a FHIR R4 Bundle.

    Returns a downloadable JSON file containing:
    - Patient resource (profile, allergies, conditions, address)
    - MedicationStatement resources (one per active/past medication)
    - Observation resources (one per lab result, with LOINC codes
      for all standard Indian panel tests)

    The Bundle conforms to FHIR R4 and can be imported into any
    FHIR-compatible EHR or PHR system (e.g. ABDM Health Locker).
    """
    firebase_uid = token_data.get("uid")

    user_result = await db.execute(
        select(UserModel).where(UserModel.firebase_uid == firebase_uid)
    )
    user = user_result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    meds_result = await db.execute(
        select(MedicationModel)
        .where(MedicationModel.user_id == user.id)
        .order_by(MedicationModel.start_date.asc())
    )
    medications = meds_result.scalars().all()

    labs_result = await db.execute(
        select(LabResultModel)
        .where(LabResultModel.user_id == user.id)
        .order_by(LabResultModel.date_taken.asc().nulls_last())
    )
    lab_results = labs_result.scalars().all()

    bundle = build_fhir_bundle(
        user=user,
        medications=list(medications),
        lab_results=list(lab_results),
    )

    filename = f"aura-fhir-export-user{user.id}.json"
    return Response(
        content=json.dumps(bundle, indent=2, ensure_ascii=False),
        media_type="application/fhir+json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Settings endpoints
# ---------------------------------------------------------------------------

class MeResponse(BaseModel):
    id: int
    email: str
    username: Optional[str]
    role: str
    phone: Optional[str]
    date_of_birth: Optional[str]
    timezone: Optional[str]
    blood_type: Optional[str]
    allergies: List[str]
    chronic_conditions: List[str]
    past_surgeries: List[str]
    family_history: Optional[str]
    emergency_contact_name: Optional[str]
    emergency_contact_relationship: Optional[str]
    emergency_contact_phone: Optional[str]

    class Config:
        from_attributes = True


class MeUpdatePayload(BaseModel):
    username: Optional[str] = None
    phone: Optional[str] = None
    date_of_birth: Optional[str] = None
    timezone: Optional[str] = None
    blood_type: Optional[str] = None
    allergies: Optional[List[str]] = None
    chronic_conditions: Optional[List[str]] = None
    past_surgeries: Optional[List[str]] = None
    family_history: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_relationship: Optional[str] = None
    emergency_contact_phone: Optional[str] = None


@router.get("/me", response_model=MeResponse)
async def get_me(
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """Return the current user's profile and settings."""
    result = await db.execute(
        select(UserModel).where(UserModel.firebase_uid == token_data["uid"])
    )
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    profile = user.medical_profile or {}
    med_history = profile.get("medical_history") or {}
    emergency = profile.get("emergency_contact") or {}
    location = profile.get("location") or {}

    return MeResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        role=user.role,
        phone=profile.get("phone"),
        date_of_birth=profile.get("date_of_birth"),
        timezone=location.get("timezone") or user.timezone,
        blood_type=med_history.get("blood_type"),
        allergies=med_history.get("allergies") or [],
        chronic_conditions=med_history.get("chronic_conditions") or [],
        past_surgeries=med_history.get("past_surgeries") or [],
        family_history=med_history.get("family_history"),
        emergency_contact_name=emergency.get("name"),
        emergency_contact_relationship=emergency.get("relationship"),
        emergency_contact_phone=emergency.get("phone"),
    )


@router.patch("/me", response_model=MeResponse)
async def update_me(
    payload: MeUpdatePayload,
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """Update display name, health info, timezone, and emergency contact."""
    result = await db.execute(
        select(UserModel).where(UserModel.firebase_uid == token_data["uid"])
    )
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.username is not None:
        user.username = payload.username.strip() or user.username

    profile = copy.deepcopy(user.medical_profile or {})

    if payload.phone is not None:
        profile["phone"] = payload.phone
    if payload.date_of_birth is not None:
        profile["date_of_birth"] = payload.date_of_birth

    # Timezone stored in both user column and profile.location
    if payload.timezone is not None:
        user.timezone = payload.timezone
        loc = profile.setdefault("location", {})
        loc["timezone"] = payload.timezone

    med_history = profile.setdefault("medical_history", {})
    if payload.blood_type is not None:
        med_history["blood_type"] = payload.blood_type
    if payload.allergies is not None:
        med_history["allergies"] = payload.allergies
    if payload.chronic_conditions is not None:
        med_history["chronic_conditions"] = payload.chronic_conditions
    if payload.past_surgeries is not None:
        med_history["past_surgeries"] = payload.past_surgeries
    if payload.family_history is not None:
        med_history["family_history"] = payload.family_history

    emergency = profile.setdefault("emergency_contact", {})
    if payload.emergency_contact_name is not None:
        emergency["name"] = payload.emergency_contact_name
    if payload.emergency_contact_relationship is not None:
        emergency["relationship"] = payload.emergency_contact_relationship
    if payload.emergency_contact_phone is not None:
        emergency["phone"] = payload.emergency_contact_phone

    user.medical_profile = profile
    flag_modified(user, "medical_profile")
    await db.commit()
    await db.refresh(user)
    logger.info("User profile updated — user_id: %s", user.id)

    # Re-read updated profile
    profile = user.medical_profile or {}
    med_history = profile.get("medical_history") or {}
    emergency = profile.get("emergency_contact") or {}
    location = profile.get("location") or {}

    return MeResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        role=user.role,
        phone=profile.get("phone"),
        date_of_birth=profile.get("date_of_birth"),
        timezone=location.get("timezone") or user.timezone,
        blood_type=med_history.get("blood_type"),
        allergies=med_history.get("allergies") or [],
        chronic_conditions=med_history.get("chronic_conditions") or [],
        past_surgeries=med_history.get("past_surgeries") or [],
        family_history=med_history.get("family_history"),
        emergency_contact_name=emergency.get("name"),
        emergency_contact_relationship=emergency.get("relationship"),
        emergency_contact_phone=emergency.get("phone"),
    )


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Permanently delete the current user's account and all associated data.
    This action is irreversible.
    """
    result = await db.execute(
        select(UserModel).where(UserModel.firebase_uid == token_data["uid"])
    )
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.delete(user)
    await db.commit()
    logger.info("User account deleted — firebase_uid: %s", token_data["uid"])
