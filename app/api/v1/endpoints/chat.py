import logging
import uuid
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.deps import get_current_user_token
from app.core.database import get_db
from app.models.user import User
from app.services.agent import aura_agent

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/chat",
    tags=["chat"],
)


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str


async def _fetch_medical_profile(
    db: AsyncSession, firebase_uid: str
) -> Optional[Dict[str, Any]]:
    """Fetch the user's medical_profile JSONB column from the database."""
    logger.debug("Fetching medical profile for uid: %s", firebase_uid)
    result = await db.execute(
        select(User.medical_profile).where(User.firebase_uid == firebase_uid)
    )
    row = result.scalar_one_or_none()
    if row is None:
        logger.debug("No medical profile found for uid: %s", firebase_uid)
    return row  # returns the dict stored in JSONB, or None


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

        # Fetch the user's medical profile (Digital Twin) from the DB
        medical_profile = await _fetch_medical_profile(db, firebase_uid=user_uid)

        # Use provided session_id or generate a new one
        session_id = request.session_id or f"session_{uuid.uuid4().hex[:8]}"
        if not request.session_id:
            logger.debug("Generated new session_id: %s", session_id)

        # Get response from the ADK Runner, passing the user's profile for context
        reply_text = await aura_agent.get_chat_response(
            message=request.message,
            session_id=session_id,
            user_id=user_uid,
            medical_profile=medical_profile,
        )

        logger.info(
            "Chat response generated — session_id: %s, reply_length: %d",
            session_id,
            len(reply_text),
        )
        return ChatResponse(reply=reply_text, session_id=session_id)

    except Exception as e:
        logger.exception(
            "Chat endpoint error for uid: %s — %s", token_data.get("uid"), e
        )
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")
