from sqlalchemy import Column, String, Integer, DateTime, Boolean, ForeignKey, Float
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base # <--- Import from core

class Doctor(Base):
    """Doctor details linked to a specific User"""
    __tablename__ = "doctors"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    
    # Professional Details
    name = Column(String, index=True)
    specialization = Column(String, index=True)
    license_number = Column(String, unique=True)
    years_of_experience = Column(Integer, default=0)
    
    # Rich data fields
    education = Column(JSONB, default=[])
    certifications = Column(JSONB, default=[])
    languages = Column(JSONB, default=[])
    
    bio = Column(String)
    consultation_fee = Column(Float, default=0.0)
    
    # Availability & Stats
    availability = Column(JSONB, default={})
    rating = Column(Float, default=0.0)
    total_consultations = Column(Integer, default=0)
    is_verified = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="doctor_profile")