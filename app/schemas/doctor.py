from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class DoctorBase(BaseModel):
    name: str
    specialization: str
    contact: str

class DoctorCreate(DoctorBase):
    pass

class DoctorUpdate(BaseModel):
    name: Optional[str] = None
    specialization: Optional[str] = None
    is_available: Optional[bool] = None

class Doctor(DoctorBase):
    id: int
    is_available: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True
