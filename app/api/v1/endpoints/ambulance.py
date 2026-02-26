from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
# from app.schemas.doctor import Doctor, DoctorCreate, DoctorUpdate
from app.core.database import get_db

router = APIRouter(
    prefix="/ambulance",
    tags=["ambulance"],
    responses={404: {"description": "Not found"}},
)

@router.get("/available")
async def get_available_ambulances(db: AsyncSession = Depends(get_db)):
    """Get available ambulances"""
    # TODO: Implement ambulance search logic
    pass

@router.get("/{ambulance_id}")
async def get_ambulance(ambulance_id: int, db: AsyncSession = Depends(get_db)):
    """Get ambulance details"""
    # TODO: Implement ambulance details logic
    pass

@router.post("/request")
async def request_ambulance(location: str, db: AsyncSession = Depends(get_db)):
    """Request an ambulance"""
    # TODO: Implement ambulance request logic
    pass
