from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.user import User, UserCreate, UserUpdate
from app.core.database import get_db

router = APIRouter(
    prefix="/users",
    tags=["users"],
    responses={404: {"description": "Not found"}},
)

@router.get("/", response_model=list[User])
async def get_users(db: AsyncSession = Depends(get_db)):
    """Get all users"""
    # TODO: Implement get all users logic
    pass

@router.get("/{user_id}", response_model=User)
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    """Get user by ID"""
    # TODO: Implement get user logic
    pass

@router.post("/", response_model=User)
async def create_user(user: UserCreate, db: AsyncSession = Depends(get_db)):
    """Create a new user"""
    # TODO: Implement create user logic
    pass

@router.put("/{user_id}", response_model=User)
async def update_user(user_id: int, user_update: UserUpdate, db: AsyncSession = Depends(get_db)):
    """Update user"""
    # TODO: Implement update user logic
    pass

@router.delete("/{user_id}")
async def delete_user(user_id: int, db: AsyncSession = Depends(get_db)):
    """Delete user"""
    # TODO: Implement delete user logic
    pass
