from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

class EducationItem(BaseModel):
    degree: str
    institution: str
    year: str  

class DoctorOnboarding(BaseModel):
    name: Optional[str] = None  # <--- Made optional
    specialization: str
    license_number: str
    years_of_experience: int
    education: List[EducationItem] = []
    certifications: List[str] = []
    languages: List[str] = []
    bio: Optional[str] = None
    consultation_fee: Optional[float] = 0.0
    availability: Optional[Dict[str, Any]] = {"days": [], "hours": ""}
    
    # Accept these fields if the frontend sends them, but make them optional
    is_verified: Optional[bool] = False
    is_available: Optional[bool] = True
    rating: Optional[float] = 0.0
    total_consultations: Optional[int] = 0

class Doctor(DoctorOnboarding):
    id: int
    user_id: int
    rating: float
    total_consultations: int
    is_verified: bool
    is_available: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

# --- NEW: Wrapped Response Model ---
class DoctorProfileResponse(BaseModel):
    message: str
    data: Doctor