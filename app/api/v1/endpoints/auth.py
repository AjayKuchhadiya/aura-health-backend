from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.user import UserCreate, User
from app.core.database import get_db

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
    responses={404: {"description": "Not found"}},
)

@router.post("/register", response_model=User)
async def register(user: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register a new user"""
    # TODO: Implement user registration logic
    pass

@router.post("/login")
async def login(email: str, password: str, db: AsyncSession = Depends(get_db)):
    """Login user and return access token"""
    # TODO: Implement login logic
    pass
