"""Medications CRUD endpoints — /api/v1/medications"""

import logging
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_token
from app.core.database import get_db
from app.models.medication import Medication as MedicationModel
from app.models.user import User as UserModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/medications", tags=["medications"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class MedicationCreate(BaseModel):
    medication_name: str
    dosage: str
    frequency: str
    start_date: date
    end_date: Optional[date] = None
    notes: Optional[str] = None


class MedicationUpdate(BaseModel):
    medication_name: Optional[str] = None
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    notes: Optional[str] = None
    google_calendar_event_id: Optional[str] = None


class MedicationRead(BaseModel):
    id: int
    user_id: int
    medication_name: str
    dosage: str
    frequency: str
    start_date: date
    end_date: Optional[date] = None
    notes: Optional[str] = None
    google_calendar_event_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _resolve_user(firebase_uid: str, db: AsyncSession) -> UserModel:
    result = await db.execute(
        select(UserModel).where(UserModel.firebase_uid == firebase_uid)
    )
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=MedicationRead, status_code=status.HTTP_201_CREATED)
async def create_medication(
    payload: MedicationCreate,
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Add a new medication to the user's regimen.

    After saving, ask Aura via POST /chat/run to schedule recurring Google
    Calendar reminders — the agent will invoke the MCP calendar tools.
    """
    user = await _resolve_user(token_data["uid"], db)
    med = MedicationModel(
        user_id=user.id,
        medication_name=payload.medication_name,
        dosage=payload.dosage,
        frequency=payload.frequency,
        start_date=payload.start_date,
        end_date=payload.end_date,
        notes=payload.notes,
    )
    db.add(med)
    await db.commit()
    await db.refresh(med)
    logger.info("Medication created — user_id: %s, med_id: %s", user.id, med.id)
    return med


@router.get("/", response_model=List[MedicationRead])
async def list_medications(
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """List all medications for the authenticated user."""
    user = await _resolve_user(token_data["uid"], db)
    result = await db.execute(
        select(MedicationModel)
        .where(MedicationModel.user_id == user.id)
        .order_by(MedicationModel.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{medication_id}", response_model=MedicationRead)
async def get_medication(
    medication_id: int,
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """Get a single medication record."""
    user = await _resolve_user(token_data["uid"], db)
    result = await db.execute(
        select(MedicationModel).where(
            MedicationModel.id == medication_id,
            MedicationModel.user_id == user.id,
        )
    )
    med = result.scalars().first()
    if not med:
        raise HTTPException(status_code=404, detail="Medication not found")
    return med


@router.patch("/{medication_id}", response_model=MedicationRead)
async def update_medication(
    medication_id: int,
    payload: MedicationUpdate,
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a medication record."""
    user = await _resolve_user(token_data["uid"], db)
    result = await db.execute(
        select(MedicationModel).where(
            MedicationModel.id == medication_id,
            MedicationModel.user_id == user.id,
        )
    )
    med = result.scalars().first()
    if not med:
        raise HTTPException(status_code=404, detail="Medication not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(med, field, value)
    med.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(med)
    logger.info("Medication updated — med_id: %s", medication_id)
    return med


@router.delete("/{medication_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_medication(
    medication_id: int,
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a medication record.

    To remove the associated Google Calendar event, send its ID to Aura via
    POST /chat/run: ``Delete calendar event <google_calendar_event_id>``.
    """
    user = await _resolve_user(token_data["uid"], db)
    result = await db.execute(
        select(MedicationModel).where(
            MedicationModel.id == medication_id,
            MedicationModel.user_id == user.id,
        )
    )
    med = result.scalars().first()
    if not med:
        raise HTTPException(status_code=404, detail="Medication not found")
    await db.delete(med)
    await db.commit()
    logger.info("Medication deleted — med_id: %s", medication_id)
