from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
import uuid

from app.api.deps import get_current_user_token
from app.services.agent import aura_agent

router = APIRouter(
    prefix="/chat",
    tags=["chat"],
)


# Pydantic Schemas for Request/Response
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str


@router.post("/run", response_model=ChatResponse)
async def run_chat(
    request: ChatRequest, token_data: dict = Depends(get_current_user_token)
):
    """
    Endpoint to interact with the Aura Health AI Assistant.
    Requires a valid Firebase Bearer token.
    """
    try:
        # If no session_id is provided, create a new one based on the user's UID and a UUID
        user_uid = token_data.get("uid", "unknown_user")
        session_id = request.session_id or f"session_{user_uid}_{uuid.uuid4().hex[:8]}"

        # Get response from the ADK Agent
        reply_text = await aura_agent.get_chat_response(
            message=request.message, session_id=session_id
        )

        return ChatResponse(reply=reply_text, session_id=session_id)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")
