from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class UserCalendarToken(Base):
    """
    Stores per-user Google Calendar OAuth tokens (encrypted at rest).

    Flow:
      1. User hits GET /api/v1/calendar/auth  -> redirected to Google
      2. Google redirects to GET /api/v1/calendar/callback with ?code=...
      3. Backend exchanges code for access_token + refresh_token
      4. Both stored here (encrypted). refresh_token is permanent; we use it
         to silently get a new access_token whenever it expires.
    """

    __tablename__ = "user_calendar_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,   # one Google Calendar connection per user
        index=True,
    )
    # Encrypted using Fernet (app SECRET_KEY derived key).
    # Never store raw tokens in the DB.
    encrypted_access_token = Column(Text, nullable=False)
    encrypted_refresh_token = Column(Text, nullable=False)
    token_expiry = Column(DateTime, nullable=True)   # UTC expiry of access_token
    google_email = Column(String, nullable=True)     # which Google account connected
    granted_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="calendar_token")
