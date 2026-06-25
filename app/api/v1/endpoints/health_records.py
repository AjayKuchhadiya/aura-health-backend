"""Health Records upload endpoint — /api/v1/health-records"""

import copy
import logging
import uuid
from datetime import datetime, date
from typing import Optional, Set

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.api.deps import get_current_user_token
from app.core.database import get_db
from app.models.lab_result import LabResult
from app.models.user import User as UserModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health-records", tags=["health-records"])


def _generate_document_title(extraction: dict, file_name: Optional[str]) -> str:
    """Generate a short human-readable title from Gemini's extraction output."""
    # Let Gemini provide it directly if the prompt returns one
    title = extraction.get("document_title")
    if title and isinstance(title, str) and title.strip():
        return title.strip()

    labs = extraction.get("lab_results", [])
    meds = extraction.get("medications", [])
    diagnoses = extraction.get("diagnoses", [])

    if labs:
        test_lower = [l.get("test_name", "").lower() for l in labs]
        if any("hba1c" in t or "glycated" in t or "fasting blood sugar" in t or "fbs" == t.strip() for t in test_lower):
            return "Diabetes Panel Report"
        if any("cholesterol" in t or "ldl" in t or "hdl" in t or "triglyceride" in t for t in test_lower):
            return "Lipid Profile Report"
        if any("tsh" in t or "t3" == t.strip() or "t4" == t.strip() for t in test_lower):
            return "Thyroid Function Report"
        if any("creatinine" in t or "urea" in t or "egfr" in t or "kft" in t or "rft" in t for t in test_lower):
            return "Kidney Function Report"
        if any("sgot" in t or "sgpt" in t or "bilirubin" in t or "lft" in t or "alt" == t.strip() for t in test_lower):
            return "Liver Function Report"
        if any("haemoglobin" in t or "hemoglobin" in t or "cbc" in t or "tlc" in t for t in test_lower):
            return "Blood Count (CBC) Report"
        if any("vitamin d" in t or "25-oh" in t for t in test_lower):
            return "Vitamin D Report"
        if any("vitamin b12" in t or "b12" in t or "cobalamin" in t for t in test_lower):
            return "Vitamin B12 Report"
        n = len(labs)
        return f"Lab Report ({n} test{'s' if n != 1 else ''})"

    if meds:
        n = len(meds)
        return f"Prescription ({n} medication{'s' if n != 1 else ''})"

    if diagnoses:
        return diagnoses[0]

    # Fall back to cleaned-up file name
    base = file_name or "Health Record"
    for ext in (".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic"):
        if base.lower().endswith(ext):
            base = base[: -len(ext)]
            break
    cleaned = base.replace("_", " ").replace("-", " ").strip()
    return cleaned.title() if cleaned else "Health Record"

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

    # Generate a unique ID for this upload so labs can be linked back to it
    upload_id = uuid.uuid4().hex

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

    # --- Merge into Digital Twin JSONB & persist structured lab rows ---
    if "error" not in extraction:
        # Deep-copy is required: plain dict() is a shallow copy, so the inner
        # health_records list is the SAME Python object as in user.medical_profile.
        # Appending to it mutates both old and new values, causing SQLAlchemy
        # (which compares old vs new for plain JSONB columns) to skip the UPDATE.
        profile = copy.deepcopy(user.medical_profile or {})

        document_title = _generate_document_title(extraction, file.filename)

        records = profile.setdefault("health_records", [])
        records.append(
            {
                "upload_id": upload_id,
                "document_title": document_title,
                "file_name": file.filename or "upload",
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
        flag_modified(user, "medical_profile")  # force SQLAlchemy to include in UPDATE

        # Persist each lab result as a typed row in the lab_results table
        doc_date_str: Optional[str] = extraction.get("document_date")
        doc_date: Optional[date] = None
        if doc_date_str:
            try:
                doc_date = date.fromisoformat(doc_date_str)
            except ValueError:
                pass

        for lab in extraction.get("lab_results", []):
            raw_value = lab.get("value")
            try:
                numeric_value = float(raw_value)
            except (TypeError, ValueError):
                logger.warning("Skipping lab result with non-numeric value: %s", raw_value)
                continue

            taken_str = lab.get("date_taken") or doc_date_str
            taken_date: Optional[date] = None
            if taken_str:
                try:
                    taken_date = date.fromisoformat(taken_str)
                except ValueError:
                    taken_date = doc_date

            db.add(LabResult(
                user_id=user.id,
                upload_id=upload_id,
                test_name=lab.get("test_name", "Unknown"),
                value=numeric_value,
                unit=lab.get("unit"),
                reference_range=lab.get("reference_range"),
                flag=lab.get("flag"),
                date_taken=taken_date,
            ))

        await db.commit()
        logger.info(
            "Health record saved — user_id: %s, labs persisted: %d",
            user.id,
            len(extraction.get("lab_results", [])),
        )

    return {
        "upload_id": upload_id,
        "file_url": public_url,
        "extraction": extraction,
        "message": (
            "Record uploaded and extracted into your Digital Twin."
            if "error" not in extraction
            else "Record uploaded but extraction had issues: " + str(extraction.get("error"))
        ),
    }


@router.get("/uploads")
async def list_uploads(
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Return a list of the user's uploaded health record files, each with
    their extracted lab results grouped underneath.
    """
    user = await _resolve_user(token_data["uid"], db)

    # Load upload metadata from JSONB
    profile = user.medical_profile or {}
    raw_records: list = profile.get("health_records", [])

    # Load all lab rows for this user, keyed by upload_id
    lab_rows = (await db.execute(
        select(LabResult).where(LabResult.user_id == user.id)
        .order_by(LabResult.date_taken.asc().nulls_last())
    )).scalars().all()

    labs_by_upload: dict[str, list] = {}
    for row in lab_rows:
        key = row.upload_id or "__unlinked__"
        labs_by_upload.setdefault(key, []).append({
            "id": row.id,
            "test_name": row.test_name,
            "value": row.value,
            "unit": row.unit,
            "reference_range": row.reference_range,
            "flag": row.flag,
            "date": row.date_taken.isoformat() if row.date_taken else None,
        })

    uploads = []
    for rec in reversed(raw_records):  # newest first
        uid = rec.get("upload_id")
        ext = rec.get("extracted_data", {})
        uploads.append({
            "upload_id": uid,
            "document_title": rec.get("document_title") or _generate_document_title(ext, rec.get("file_name")),
            "file_name": rec.get("file_name", "Health Record"),
            "file_url": rec.get("file_url"),
            "uploaded_at": rec.get("uploaded_at"),
            "lab_count": len(labs_by_upload.get(uid or "", [])),
            "medication_count": len(ext.get("medications", [])),
            "diagnoses": ext.get("diagnoses", []),
            "medications": ext.get("medications", []),
            "doctor_name": ext.get("doctor_name"),
            "clinic_name": ext.get("clinic_name"),
            "document_date": ext.get("document_date"),
            "notes": ext.get("notes"),
            "labs": labs_by_upload.get(uid or "", []),
        })

    return {"total": len(uploads), "uploads": uploads}


@router.delete("/uploads/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_upload(
    upload_id: str,
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete an uploaded health record and all its extracted lab results.
    Also removes the file from Supabase Storage and the JSONB profile entry.
    """
    user = await _resolve_user(token_data["uid"], db)

    # Find the record in JSONB to get the storage path
    profile = dict(user.medical_profile or {})
    records: list = profile.get("health_records", [])
    target = next((r for r in records if r.get("upload_id") == upload_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Upload not found.")

    # Delete from Supabase Storage (non-fatal if it fails)
    file_url: str = target.get("file_url", "")
    if file_url:
        try:
            from app.services.storage import delete_health_record as storage_delete
            # Extract the object path from the URL: everything after /object/public/health-records/
            marker = "/object/public/health-records/"
            if marker in file_url:
                object_path = file_url.split(marker, 1)[1]
                await storage_delete(object_path)
        except Exception as exc:
            logger.warning("Storage delete failed (non-fatal): %s", exc)

    # Delete lab rows
    await db.execute(
        delete(LabResult).where(
            LabResult.user_id == user.id,
            LabResult.upload_id == upload_id,
        )
    )

    # Remove JSONB entry
    new_profile = copy.deepcopy(profile)
    new_profile["health_records"] = [r for r in records if r.get("upload_id") != upload_id]
    user.medical_profile = new_profile
    flag_modified(user, "medical_profile")
    await db.commit()
    logger.info("Upload deleted — user_id: %s, upload_id: %s", user.id, upload_id)


@router.get("/labs/timeline")
async def get_labs_timeline(
    test_name: Optional[str] = None,
    token_data: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Return a user's lab results sorted chronologically.

    Optionally filter by test_name (case-insensitive substring match).
    Response shape is ready for Recharts / Tremor time-series charts:
    each entry has { date, test_name, value, unit, reference_range, flag }.
    """
    user = await _resolve_user(token_data["uid"], db)

    stmt = (
        select(LabResult)
        .where(LabResult.user_id == user.id)
        .order_by(LabResult.date_taken.asc().nulls_last(), LabResult.created_at.asc())
    )
    if test_name:
        stmt = stmt.where(LabResult.test_name.ilike(f"%{test_name}%"))

    result = await db.execute(stmt)
    rows = result.scalars().all()

    data = [
        {
            "id": row.id,
            "test_name": row.test_name,
            "value": row.value,
            "unit": row.unit,
            "reference_range": row.reference_range,
            "flag": row.flag,
            "date": row.date_taken.isoformat() if row.date_taken else None,
        }
        for row in rows
    ]

    return {"total": len(data), "results": data}
