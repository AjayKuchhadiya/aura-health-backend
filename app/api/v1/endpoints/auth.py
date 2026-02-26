from pydantic import BaseModel
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query # <--- Import Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.schemas.patient import Patient as PatientSchema
from app.models.user import User as UserModel
from app.core.database import get_db
from app.api.deps import get_current_user_token

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)
class SignupRequest(BaseModel):
    name: Optional[str] = None
    role: str = "patient" 

@router.post("/signup", response_model=PatientSchema, status_code=status.HTTP_201_CREATED)
async def signup(
    signup_data: SignupRequest,
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db)
):
    """
    Registration Endpoint:
    Call this ONLY when a user signs up for the first time.
    It creates their record in Postgres.
    """
    # VALIDATE THE ROLE (Security best practice)
    if signup_data.role not in ["patient", "doctor"]:
        raise HTTPException(
            status_code=400, 
            detail="Invalid role. Must be 'patient' or 'doctor'."
        )

    firebase_uid = token_data.get("uid")
    email = token_data.get("email")

    # Check if user already exists
    result = await db.execute(select(UserModel).where(UserModel.firebase_uid == firebase_uid))
    existing_user = result.scalars().first()

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="User already registered. Please log in."
        )

    # Determine the username
    final_username = signup_data.name if signup_data.name else email.split("@")[0]

    # 3. Create new user
    new_user = UserModel(
        firebase_uid=firebase_uid,
        email=email,
        username=final_username, 
        role=signup_data.role, 
        medical_profile={}
    )
    
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    
    return new_user


@router.post("/login", response_model=PatientSchema)
async def login(
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db)
):
    """
    Login Endpoint:
    Call this when a returning user signs in.
    It retrieves their profile from Postgres.
    """
    firebase_uid = token_data.get("uid")

    # 1. Fetch user
    result = await db.execute(select(UserModel).where(UserModel.firebase_uid == firebase_uid))
    user = result.scalars().first()

    # 2. Strict Check: If they aren't in Postgres, they haven't signed up
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User profile not found. Please sign up first."
        )
    
    return user


@router.get("/me", response_model=PatientSchema)
async def get_current_user_profile(
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db)
):
    """
    Get Current User Endpoint:
    Call this on app load or page refresh.
    It returns the user's profile based on their active Firebase token.
    """
    firebase_uid = token_data.get("uid")

    # 1. Fetch user by their Firebase UID
    result = await db.execute(select(UserModel).where(UserModel.firebase_uid == firebase_uid))
    user = result.scalars().first()

    # 2. If no database record is found, they need to be redirected to signup
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found. Please complete the registration process."
        )

    return user