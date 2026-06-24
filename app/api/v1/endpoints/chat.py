import logging
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.api.deps import get_current_user_token
from app.core.database import get_db
from app.models.user import User
from app.services.agent import aura_agent

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/chat",
    tags=["chat"],
)


class LocationPayload(BaseModel):
    """User's current location sent by the frontend on every chat request."""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    city: Optional[str] = None
    country: Optional[str] = None
    timezone: Optional[str] = None  # e.g. 'America/Los_Angeles'


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    location: Optional[LocationPayload] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str


async def _fetch_medical_profile(
    db: AsyncSession, firebase_uid: str
) -> tuple[Optional[Dict[str, Any]], Optional[int]]:
    """Fetch the user's medical_profile JSONB column and DB id from the database."""
    logger.debug("Fetching medical profile for uid: %s", firebase_uid)
    result = await db.execute(
        select(User.medical_profile, User.id).where(User.firebase_uid == firebase_uid)
    )
    row = result.first()
    if row is None:
        logger.debug("No user found for uid: %s", firebase_uid)
        return None, None
    return row[0], row[1]  # (medical_profile dict, db id)


@router.post("/run", response_model=ChatResponse)
async def run_chat(
    request: ChatRequest,
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Endpoint to interact with the Aura Health AI Assistant.
    Requires a valid Firebase Bearer token.
    The user's medical profile (Digital Twin) is fetched from the database
    and passed to the agent so it has full context for every conversation.
    """
    try:
        # Extract user ID from Firebase token
        user_uid = token_data.get("uid", "unknown_user")
        logger.info(
            "Chat request — uid: %s, session_id: %s, message_length: %d",
            user_uid,
            request.session_id or "(new)",
            len(request.message),
        )

        # Fetch the user's medical profile (Digital Twin) and DB id from the DB
        medical_profile, user_db_id = await _fetch_medical_profile(db, firebase_uid=user_uid)

        # Persist user's location if provided
        location_dict: Optional[Dict[str, Any]] = None
        if request.location:
            location_dict = request.location.model_dump(exclude_none=True)
            await db.execute(
                update(User)
                .where(User.firebase_uid == user_uid)
                .values(
                    last_known_latitude=request.location.latitude,
                    last_known_longitude=request.location.longitude,
                    last_known_city=request.location.city,
                    last_known_country=request.location.country,
                    timezone=request.location.timezone,
                    location_updated_at=datetime.utcnow(),
                )
            )
            await db.commit()
            logger.debug("Location updated for uid: %s — %s", user_uid, location_dict)

        # Use provided session_id or generate a new one
        session_id = request.session_id or f"session_{uuid.uuid4().hex[:8]}"
        if not request.session_id:
            logger.debug("Generated new session_id: %s", session_id)

        # Get response from the ADK Runner, passing the user's profile and DB id
        reply_text = await aura_agent.get_chat_response(
            message=request.message,
            session_id=session_id,
            user_id=user_uid,
            user_db_id=user_db_id,
            medical_profile=medical_profile,
        )

        logger.info(
            "Chat response generated — session_id: %s, reply_length: %d",
            session_id,
            len(reply_text),
        )
        return ChatResponse(reply=reply_text, session_id=session_id)

    except HTTPException:
        raise  # re-raise FastAPI exceptions unchanged

    except Exception as e:
        err_str = str(e)
        # Gemini 503 — model overloaded
        if "503" in err_str or "UNAVAILABLE" in err_str:
            logger.warning(
                "Gemini 503 for uid: %s — %s", token_data.get("uid"), err_str
            )
            raise HTTPException(
                status_code=503,
                detail=(
                    "Aura's AI engine is experiencing high demand right now. "
                    "Please wait a moment and try again."
                ),
            )
        # Gemini 429 — free-tier quota exhausted
        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
            logger.warning(
                "Gemini 429 for uid: %s — %s", token_data.get("uid"), err_str
            )
            raise HTTPException(
                status_code=429,
                detail=(
                    "Aura has reached its daily request limit. "
                    "Please try again tomorrow or contact support to upgrade the plan."
                ),
            )
        logger.exception(
            "Chat endpoint error for uid: %s — %s", token_data.get("uid"), e
        )
        raise HTTPException(status_code=500, detail=f"Agent error: {err_str}")
