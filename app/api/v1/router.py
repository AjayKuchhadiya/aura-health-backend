from fastapi import APIRouter
from .endpoints import auth, users, ambulance, chat

router = APIRouter()

# Include endpoint routers
router.include_router(auth.router)
router.include_router(users.router)
router.include_router(ambulance.router)
router.include_router(chat.router)
