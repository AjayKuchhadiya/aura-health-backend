import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.firebase import verify_id_token

logger = logging.getLogger(__name__)

security = HTTPBearer()


async def get_current_user_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Dependency to verify the Bearer token.
    Returns the decoded Firebase token (containing uid, email, etc.)
    """
    token = credentials.credentials
    logger.debug("Verifying Bearer token (length=%d)", len(token))
    payload = verify_id_token(token)
    if not payload:
        logger.warning("Token verification failed — returning 401")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    logger.debug("Token verified for uid: %s", payload.get("uid"))
    return payload
