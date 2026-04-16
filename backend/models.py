from pydantic import BaseModel, HttpUrl, field_validator
from datetime import datetime
from typing import Optional, Literal


# ─── Clip schemas ────────────────────────────────────────────────────────────

class ClipCreate(BaseModel):
    name: str = ""
    prompt: str
    image_url: str
    end_image_url: Optional[str] = None
    resolution: Literal["480p", "720p"] = "720p"
    duration: Literal["auto", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15"] = "auto"
    aspect_ratio: Literal["auto", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"] = "auto"
    generate_audio: bool = True
    seed: Optional[int] = None
    order: int = 0


class ClipUpdate(BaseModel):
    name: Optional[str] = None
    prompt: Optional[str] = None
    image_url: Optional[str] = None
    end_image_url: Optional[str] = None
    resolution: Optional[Literal["480p", "720p"]] = None
    duration: Optional[Literal["auto", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15"]] = None
    aspect_ratio: Optional[Literal["auto", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]] = None
    generate_audio: Optional[bool] = None
    seed: Optional[int] = None
    order: Optional[int] = None


class ClipResponse(BaseModel):
    id: int
    project_id: int
    order: int
    name: str
    prompt: str
    image_url: str
    end_image_url: Optional[str]
    resolution: str
    duration: str
    aspect_ratio: str
    generate_audio: bool
    seed: Optional[int]
    status: str
    fal_request_id: Optional[str]
    video_url: Optional[str]
    video_seed: Optional[int]
    error_message: Optional[str]
    duration_seconds: Optional[float]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─── Project schemas ──────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class ProjectResponse(BaseModel):
    id: int
    name: str
    description: str
    status: str
    final_video_url: Optional[str]
    created_at: datetime
    updated_at: datetime
    clips: list[ClipResponse] = []

    model_config = {"from_attributes": True}


class ProjectSummary(BaseModel):
    id: int
    name: str
    description: str
    status: str
    final_video_url: Optional[str]
    clip_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─── Render schemas ───────────────────────────────────────────────────────────

class RenderRequest(BaseModel):
    clip_ids: Optional[list[int]] = None  # None = render all clips in project
    parallel: bool = False  # render clips in parallel vs sequential
    stitch: bool = True  # stitch clips after all complete


class RenderStatusResponse(BaseModel):
    project_id: int
    project_status: str
    final_video_url: Optional[str]
    clips: list[ClipResponse]
    total: int
    pending: int
    queued: int
    generating: int
    complete: int
    error: int


# ─── Upload schema ────────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    url: str
    filename: str
