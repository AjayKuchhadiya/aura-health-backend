from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class Medication(Base):
    """Tracks a user's active medication regimen."""

    __tablename__ = "medications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    medication_name = Column(String, nullable=False)
    dosage = Column(String, nullable=False)       # e.g. "500mg"
    frequency = Column(String, nullable=False)    # e.g. "twice daily"
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    notes = Column(String, nullable=True)
    # Populated after the agent creates a Google Calendar event via MCP
    google_calendar_event_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="medications")
