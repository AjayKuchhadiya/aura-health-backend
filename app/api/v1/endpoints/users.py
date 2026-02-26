from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db
from app.api.deps import get_current_user_token
from app.models.user import User as UserModel
from app.models.doctor import Doctor as DoctorModel
from app.schemas.patient import PatientOnboarding, PatientProfileResponse
from app.schemas.doctor import DoctorOnboarding, DoctorProfileResponse

router = APIRouter(
    prefix="/users",
    tags=["users"],
)

@router.post("/patient-profile", response_model=PatientProfileResponse)
async def onboard_patient(
    onboarding_data: PatientOnboarding,
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db)
):
    """
    Create/Update Patient Profile
    """
    firebase_uid = token_data.get("uid")
    
    result = await db.execute(select(UserModel).where(UserModel.firebase_uid == firebase_uid))
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Store the entire payload in the JSONB column
    user.medical_profile = onboarding_data.model_dump()
    user.role = "patient"
    
    await db.commit()
    await db.refresh(user)
    
    # Return wrapped response matching the contract
    return {
        "message": "Patient profile created successfully",
        "data": user
    }


@router.post("/doctor-profile", response_model=DoctorProfileResponse)
async def onboard_doctor(
    onboarding_data: DoctorOnboarding,
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db)
):
    """
    Create/Update Doctor Profile
    """
    firebase_uid = token_data.get("uid")
    
    result = await db.execute(select(UserModel).where(UserModel.firebase_uid == firebase_uid))
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    doc_result = await db.execute(select(DoctorModel).where(DoctorModel.user_id == user.id))
    existing_doctor = doc_result.scalars().first()
    
    if existing_doctor:
        raise HTTPException(status_code=400, detail="Doctor profile already exists for this user")

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
        availability=onboarding_data.availability
    )
    
    db.add(new_doctor)
    await db.commit()
    await db.refresh(new_doctor)
    
    # Return wrapped response matching the contract
    return {
        "message": "Doctor profile created successfully",
        "data": new_doctor
    }