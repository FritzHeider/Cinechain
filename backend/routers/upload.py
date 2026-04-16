from fastapi import APIRouter, UploadFile, File, Depends
from models import UploadResponse
from services.upload_service import save_and_upload

router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("/image", response_model=UploadResponse)
async def upload_image(file: UploadFile = File(...)):
    """
    Upload an image (JPEG, PNG, WebP) to fal.ai storage.
    Returns a public URL suitable for use as image_url or end_image_url in clips.
    """
    url = await save_and_upload(file)
    return UploadResponse(url=url, filename=file.filename or "image")
