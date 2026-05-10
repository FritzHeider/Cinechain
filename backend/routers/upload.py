from fastapi import APIRouter, UploadFile, File
from models import UploadResponse
from services.upload_service import save_and_upload, save_and_upload_media

router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("/image", response_model=UploadResponse)
async def upload_image(file: UploadFile = File(...)):
    """
    Upload an image (JPEG, PNG, WebP) to fal.ai storage.
    Returns a public URL suitable for use as image_url or end_image_url in clips.
    """
    url = await save_and_upload(file)
    return UploadResponse(url=url, filename=file.filename or "image")


@router.post("/media", response_model=UploadResponse)
async def upload_media(file: UploadFile = File(...)):
    """
    Upload a video (MP4/MOV/WebM ≤500 MB) or audio (MP3/WAV ≤50 MB) to fal.ai storage.
    Returns a public URL for use as reference_video_urls or reference_audio_urls in reference clips.
    """
    url = await save_and_upload_media(file)
    return UploadResponse(url=url, filename=file.filename or "media")
