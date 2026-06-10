from fastapi import APIRouter
from .endpoints import auth, users, chat, medications, health_records

router = APIRouter()

router.include_router(auth.router)
router.include_router(users.router)
router.include_router(chat.router)
router.include_router(medications.router)
router.include_router(health_records.router)
