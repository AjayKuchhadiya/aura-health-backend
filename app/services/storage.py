"""Supabase Storage service for health record file uploads (free tier)."""

import logging
import uuid

from app.core.config import settings

logger = logging.getLogger(__name__)

_BUCKET = "health-records"


def _get_client():
    """Return a synchronous Supabase client (used in run_in_executor context)."""
    from supabase import create_client
    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_KEY must be set to use file storage."
        )
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)


async def upload_health_record(
    file_bytes: bytes,
    filename: str,
    content_type: str,
    user_id: str,
) -> str:
    """
    Upload a health record file to the Supabase 'health-records' bucket.

    Files are stored at:  {user_id}/{uuid4}_{original_filename}

    Returns the public URL of the uploaded file.
    """
    import asyncio

    # Build a unique storage path scoped to the user
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    object_path = f"{user_id}/{uuid.uuid4().hex}.{ext}"

    def _upload():
        client = _get_client()
        client.storage.from_(_BUCKET).upload(
            path=object_path,
            file=file_bytes,
            file_options={"content-type": content_type, "upsert": "false"},
        )
        return client.storage.from_(_BUCKET).get_public_url(object_path)

    # Supabase Python client is sync — offload to a thread so we don't block
    loop = asyncio.get_event_loop()
    public_url: str = await loop.run_in_executor(None, _upload)
    logger.info("Uploaded health record — path: %s, url: %s", object_path, public_url)
    return public_url


async def delete_health_record(object_path: str) -> None:
    """Delete a file from the Supabase 'health-records' bucket by its storage path."""
    import asyncio

    def _delete():
        _get_client().storage.from_(_BUCKET).remove([object_path])

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _delete)
    logger.info("Deleted health record — path: %s", object_path)
