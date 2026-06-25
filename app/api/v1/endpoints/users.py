import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

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
