"""
Upload service: accepts uploaded images, saves locally, optionally pushes to fal storage.
"""

import uuid
import aiofiles
import logging
from pathlib import Path

from fastapi import UploadFile, HTTPException

from config import settings
from services.fal_service import upload_image as fal_upload_image

logger = logging.getLogger(__name__)

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_SIZE_BYTES = 30 * 1024 * 1024  # 30 MB


async def save_and_upload(file: UploadFile) -> str:
    """
    Save uploaded image locally, upload to fal storage, return public URL.
    """
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {file.content_type}. Use JPEG, PNG, or WebP.")

    content = await file.read()
    if len(content) > MAX_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="Image exceeds 30 MB limit.")

    ext = Path(file.filename or "image.jpg").suffix or ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    local_path = settings.upload_dir / filename

    async with aiofiles.open(local_path, "wb") as f:
        await f.write(content)

    logger.info(f"Saved uploaded image to {local_path}")

    try:
        public_url = await fal_upload_image(str(local_path))
        return public_url
    except Exception as e:
        logger.error(f"fal upload failed: {e}")
        raise HTTPException(status_code=502, detail=f"Image upload to fal storage failed: {e}")
