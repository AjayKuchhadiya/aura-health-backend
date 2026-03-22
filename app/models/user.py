from sqlalchemy import Column, String, Integer, DateTime, Boolean, Float
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base  # <--- Import from core


class User(Base):
    """User database model (Patients & Doctors)"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    firebase_uid = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, index=True)
    role = Column(String, default="patient")  # 'patient', 'doctor', 'admin'

    # Stores the patient's medical history, allergies, etc.
    medical_profile = Column(JSONB, default={})

    # Last known location — updated on every chat request that includes location
    last_known_latitude = Column(Float, nullable=True)
    last_known_longitude = Column(Float, nullable=True)
    last_known_city = Column(String, nullable=True)
    last_known_country = Column(String, nullable=True)
    timezone = Column(String, nullable=True)  # e.g. 'America/Los_Angeles'
    location_updated_at = Column(DateTime, nullable=True)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    doctor_profile = relationship("Doctor", back_populates="user", uselist=False)
