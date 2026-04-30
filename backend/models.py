import ipaddress
from urllib.parse import urlparse

from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional, Literal


# ─── Clip schemas ────────────────────────────────────────────────────────────

TRANSITION_TYPES = Literal[
    "fade", "wipeleft", "wiperight", "wipeup", "wipedown",
    "dissolve", "circleopen", "circleclose", "slidedown", "slideup",
    "slideleft", "slideright", "smoothleft", "smoothright", "radial",
]

_SKIP_VALIDATION = {"", "https://example.com/placeholder.jpg"}


def _validate_public_url(v: str | None) -> str | None:
    """Block private/loopback IPs and non-http(s) schemes to prevent SSRF."""
    if not v or v in _SKIP_VALIDATION:
        return v
    try:
        parsed = urlparse(v)
    except Exception:
        return v
    if parsed.scheme not in ("http", "https"):
        raise ValueError("image URL must use http or https")
    host = parsed.hostname or ""
    if not host or host == "localhost":
        raise ValueError("image URL must not point to localhost")
    try:
        addr = ipaddress.ip_address(host)
        if not addr.is_global:
            raise ValueError(f"image URL must point to a public address, not {host}")
    except ValueError as e:
        if "does not appear" not in str(e) and "is not a valid" not in str(e):
            raise  # re-raise only the SSRF check failure, not parse errors
    return v


class ClipCreate(BaseModel):
    name: str = ""
    prompt: str = ""
    image_url: str
    end_image_url: Optional[str] = None
    resolution: Literal["480p", "720p"] = "720p"
    duration: Literal["auto", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15"] = "auto"
    aspect_ratio: Literal["auto", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"] = "auto"
    generate_audio: bool = True
    seed: Optional[int] = None
    order: int = 0
    transition_type: str = "fade"
    is_passthrough: bool = False

    @field_validator("image_url", "end_image_url", mode="before")
    @classmethod
    def validate_image_urls(cls, v):
        return _validate_public_url(v)


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
    transition_type: Optional[str] = None

    @field_validator("image_url", "end_image_url", mode="before")
    @classmethod
    def validate_image_urls(cls, v):
        return _validate_public_url(v)


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
    transition_type: str
    is_passthrough: bool
    status: str
    fal_request_id: Optional[str]
    video_url: Optional[str]
    thumbnail_url: Optional[str]
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
    draft: bool = False  # use 480p for a fast/cheap preview render
    crossfade: bool = True
    crossfade_duration: float = 0.5
    max_retries: int = 3
    auto_chain: bool = False  # extract last frame of each clip → start of next


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
