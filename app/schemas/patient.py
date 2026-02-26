from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime

# --- Shared Properties ---
class PatientBase(BaseModel):
    email: EmailStr
    username: Optional[str] = None

class PatientCreate(PatientBase):
    password: str

class PatientLogin(BaseModel):
    email: EmailStr
    password: str

# --- Patient Onboarding Nested Models ---
class LocationDetails(BaseModel):
    city: Optional[str] = ""
    state: Optional[str] = ""
    country: Optional[str] = ""
    timezone: Optional[str] = ""
    postal_code: Optional[str] = ""

class MedicalHistory(BaseModel):
    blood_type: Optional[str] = ""
    allergies: List[str] = []
    chronic_conditions: List[str] = []
    past_surgeries: List[str] = []
    family_history: Optional[str] = ""

class Insurance(BaseModel):
    provider: Optional[str] = ""
    policy_number: Optional[str] = ""
    group_number: Optional[str] = ""

class EmergencyContact(BaseModel):
    name: Optional[str] = ""
    relationship: Optional[str] = ""
    phone: Optional[str] = ""

class PatientOnboarding(BaseModel):
    date_of_birth: Optional[str] = ""
    phone: Optional[str] = ""
    location: Optional[LocationDetails] = None
    medical_history: Optional[MedicalHistory] = None
    insurance: Optional[Insurance] = None
    emergency_contact: Optional[EmergencyContact] = None
    onboarding_completed: Optional[bool] = True  

# --- Database / Response Models ---
class Patient(PatientBase):
    id: int
    firebase_uid: str
    role: str
    medical_profile: Optional[Dict[str, Any]] = {}
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# --- NEW: Wrapped Response Model ---
class PatientProfileResponse(BaseModel):
    message: str
    data: Patient
    
class Token(BaseModel):
    access_token: str
    token_type: str
    patient: Patient
