"""
Upload service: accepts images, video, and audio; saves locally and pushes to fal storage.
"""

import uuid
import aiofiles
import logging
from pathlib import Path

from fastapi import UploadFile, HTTPException

from config import settings
from services.fal_service import upload_image as fal_upload_image

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 30 * 1024 * 1024  # 30 MB

_VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm"}
_VIDEO_EXTS = {".mp4", ".mov", ".webm"}
_AUDIO_TYPES = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/wave"}
_AUDIO_EXTS = {".mp3", ".wav"}
MAX_VIDEO_BYTES = 500 * 1024 * 1024  # 500 MB
MAX_AUDIO_BYTES = 50 * 1024 * 1024   # 50 MB


async def save_and_upload(file: UploadFile) -> str:
    """Save uploaded image locally, upload to fal storage, return public URL."""
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {file.content_type}. Use JPEG, PNG, or WebP.")

    content = await file.read()
    if len(content) > MAX_IMAGE_BYTES:
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


async def save_and_upload_media(file: UploadFile) -> str:
    """
    Accept video (MP4/MOV/WebM ≤500 MB) or audio (MP3/WAV ≤50 MB),
    stream to disk, upload to fal storage, return public URL.
    """
    ext = Path(file.filename or "media").suffix.lower()
    is_video = file.content_type in _VIDEO_TYPES or ext in _VIDEO_EXTS
    is_audio = file.content_type in _AUDIO_TYPES or ext in _AUDIO_EXTS

    if not is_video and not is_audio:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported media type: {file.content_type}. Use MP4/MOV/WebM for video or MP3/WAV for audio.",
        )

    max_size = MAX_VIDEO_BYTES if is_video else MAX_AUDIO_BYTES
    default_ext = ".mp4" if is_video else ".mp3"
    filename = f"{uuid.uuid4().hex}{ext or default_ext}"
    local_path = settings.upload_dir / filename

    total_bytes = 0
    _CHUNK = 1 << 20  # 1 MiB

    try:
        async with aiofiles.open(local_path, "wb") as f:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_size:
                    local_path.unlink(missing_ok=True)
                    limit = "500 MB" if is_video else "50 MB"
                    raise HTTPException(status_code=400, detail=f"File exceeds {limit} limit.")
                await f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        local_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

    logger.info(f"Saved uploaded media to {local_path} ({total_bytes // 1024} KB)")

    try:
        public_url = await fal_upload_image(str(local_path))
        return public_url
    except Exception as e:
        logger.error(f"fal media upload failed: {e}")
        raise HTTPException(status_code=502, detail=f"Media upload to fal storage failed: {e}")
    finally:
        local_path.unlink(missing_ok=True)
