"""Health Records upload endpoint — /api/v1/health-records"""

import logging
from datetime import datetime
from typing import Set

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_token
from app.core.database import get_db
from app.models.user import User as UserModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health-records", tags=["health-records"])

_ALLOWED_MIME: Set[str] = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "application/pdf",
}
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB free-tier guard


async def _resolve_user(firebase_uid: str, db: AsyncSession) -> UserModel:
    result = await db.execute(
        select(UserModel).where(UserModel.firebase_uid == firebase_uid)
    )
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_health_record(
    file: UploadFile = File(...),
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a health record (prescription image or lab-report PDF).

    Pipeline:
      1. Validate MIME type and size (10 MB cap).
      2. Upload to Supabase Storage bucket 'health-records'.
      3. Pass file bytes to Gemini 2.5 Flash multimodal for structured extraction.
      4. Merge extracted data into the user's medical_profile JSONB (Digital Twin).
      5. Return the public file URL and extraction result.
    """
    if file.content_type not in _ALLOWED_MIME:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{file.content_type}'. "
                f"Allowed: {', '.join(sorted(_ALLOWED_MIME))}"
            ),
        )

    file_bytes = await file.read()
    if len(file_bytes) > _MAX_BYTES:
        raise HTTPException(
            status_code=413, detail="File exceeds the 10 MB size limit."
        )

    user = await _resolve_user(token_data["uid"], db)

    # --- Upload to Supabase Storage ---
    from app.services.storage import upload_health_record as storage_upload

    try:
        public_url = await storage_upload(
            file_bytes=file_bytes,
            filename=file.filename or "upload",
            content_type=file.content_type,
            user_id=str(user.id),
        )
    except Exception as exc:
        logger.exception("Supabase storage upload failed")
        raise HTTPException(status_code=502, detail=f"Storage upload failed: {exc}")

    # --- Gemini multimodal extraction ---
    from app.services.ocr import extract_medical_data

    extraction = await extract_medical_data(file_bytes, file.content_type)

    # --- Merge into Digital Twin JSONB ---
    if "error" not in extraction:
        profile = dict(user.medical_profile or {})

        records = profile.setdefault("health_records", [])
        records.append(
            {
                "file_url": public_url,
                "uploaded_at": datetime.utcnow().isoformat(),
                "extracted_data": extraction,
            }
        )

        # Surface newly found medications at the profile top level for the agent
        existing_meds = profile.setdefault("current_medications", [])
        for med in extraction.get("medications", []):
            if med not in existing_meds:
                existing_meds.append(med)

        user.medical_profile = profile
        await db.commit()
        logger.info("Health record saved to Digital Twin — user_id: %s", user.id)

    return {
        "file_url": public_url,
        "extraction": extraction,
        "message": (
            "Record uploaded and extracted into your Digital Twin."
            if "error" not in extraction
            else "Record uploaded but extraction had issues: " + str(extraction.get("error"))
        ),
    }
