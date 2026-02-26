from fastapi import APIRouter
from app.api.v1.endpoints import auth, users, ambulance

router = APIRouter()

# Include endpoint routers
router.include_router(auth.router)
router.include_router(users.router)
router.include_router(ambulance.router)
