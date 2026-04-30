"""
Extend router: upload a movie short and auto-generate a continuation storyboard.

POST /projects/{id}/extend
  - Accepts a video file (mp4/mov/webm, up to 500 MB)
  - Extracts frames → Claude Opus analyzes characters + story → generates N scenes
  - Creates clip 0 = original video (status=complete, video_url already set)
  - Creates clips 1..N with AI-generated prompts; first new clip's image_url = last frame
  - Returns {character_anchors, visual_style, story_so_far, clips}
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import settings
from database import get_db, Clip, Project
from models import ClipResponse
from services import extend_service, fal_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["extend"])

ALLOWED_VIDEO_TYPES = {
    "video/mp4", "video/quicktime", "video/webm", "video/x-msvideo",
    "video/x-matroska", "video/mpeg",
}
MAX_VIDEO_BYTES = 500 * 1024 * 1024  # 500 MB


@router.post("/{project_id}/extend")
async def extend_from_video(
    project_id: int,
    video: UploadFile = File(...),
    n_scenes: int = Form(4),
    resolution: str = Form("720p"),
    aspect_ratio: str = Form("16:9"),
    duration: str = Form("8"),
    generate_audio: bool = Form(True),
    db: AsyncSession = Depends(get_db),
):
    # ── Validate project ──────────────────────────────────────────────────────
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # ── Validate video upload ─────────────────────────────────────────────────
    if video.content_type not in ALLOWED_VIDEO_TYPES and not (
        video.filename or ""
    ).lower().endswith((".mp4", ".mov", ".webm", ".avi", ".mkv", ".mpeg")):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported video type: {video.content_type}. Use MP4, MOV, WebM, or AVI.",
        )

    n_scenes = max(1, min(n_scenes, 12))

    # ── Stream video to disk (avoids loading 500 MB into RAM) ────────────────
    ext = Path(video.filename or "video.mp4").suffix or ".mp4"
    vid_filename = f"upload_{uuid.uuid4().hex}{ext}"
    vid_path = settings.upload_dir / vid_filename

    total_bytes = 0
    _CHUNK = 1 << 20  # 1 MiB
    try:
        with open(vid_path, "wb") as f:
            while True:
                chunk = await video.read(_CHUNK)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_VIDEO_BYTES:
                    vid_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=400, detail="Video exceeds 500 MB limit.")
                f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        vid_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

    logger.info(f"Saved uploaded video to {vid_path} ({total_bytes // 1024} KB)")

    try:
        # ── Analyze with Claude ───────────────────────────────────────────────
        logger.info(f"Analyzing video with Claude Opus for project {project_id}…")
        storyboard = await extend_service.analyze_and_extend(
            video_path=str(vid_path),
            n_scenes=n_scenes,
            project_name=project.name,
        )

        # ── Upload original video to fal storage ──────────────────────────────
        logger.info("Uploading original video to fal storage…")
        original_video_url = await fal_service.upload_image(str(vid_path))

        # ── Extract first frame for original clip thumbnail ───────────────────
        first_frame_list = await asyncio.to_thread(
            extend_service.extract_frames_sync, str(vid_path), 1
        )
        first_frame = first_frame_list[0] if first_frame_list else None

        first_frame_url = ""
        if first_frame:
            ff_filename = f"frame_first_{uuid.uuid4().hex[:8]}.jpg"
            ff_path = settings.upload_dir / ff_filename
            ff_path.write_bytes(first_frame)
            first_frame_url = await fal_service.upload_image(str(ff_path))

        # ── Extract last frame → start image for first new clip ───────────────
        logger.info("Extracting last frame for chaining…")
        last_frame_bytes = await extend_service.extract_last_frame(str(vid_path))
        lf_filename = f"frame_last_{uuid.uuid4().hex[:8]}.jpg"
        lf_path = settings.upload_dir / lf_filename
        lf_path.write_bytes(last_frame_bytes)
        last_frame_url = await fal_service.upload_image(str(lf_path))

    except Exception as e:
        logger.error(f"Extend failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Always remove the raw upload — it's been uploaded to fal CDN or isn't needed
        vid_path.unlink(missing_ok=True)

    # ── Determine order offset (append after existing clips) ──────────────────
    existing = await db.execute(
        select(Clip).where(Clip.project_id == project_id).order_by(Clip.order.desc())
    )
    max_order = (existing.scalars().first() or None)
    order_start = (max_order.order + 1) if max_order else 0

    created_clips: list[Clip] = []

    # ── Clip 0: original video (already generated, skip re-generation) ──────────
    original_clip = Clip(
        project_id=project_id,
        order=order_start,
        name="Original Short",
        prompt="[Original uploaded video — passthrough]",
        image_url=first_frame_url or original_video_url,
        resolution=resolution,
        duration=duration,
        aspect_ratio=aspect_ratio,
        generate_audio=generate_audio,
        is_passthrough=True,
        status="complete",
        video_url=original_video_url,
    )
    db.add(original_clip)
    await db.flush()
    created_clips.append(original_clip)

    # ── Continuation clips from storyboard ────────────────────────────────────
    scenes = storyboard.get("scenes", [])
    for i, scene in enumerate(scenes):
        # First new clip's image_url = last frame of original video
        img_url = last_frame_url if i == 0 else ""
        clip = Clip(
            project_id=project_id,
            order=order_start + 1 + i,
            name=scene.get("name", f"Scene {i + 1}"),
            prompt=scene.get("prompt", ""),
            image_url=img_url,
            resolution=resolution,
            duration=duration,
            aspect_ratio=aspect_ratio,
            generate_audio=generate_audio,
            status="pending",
        )
        db.add(clip)
        await db.flush()
        created_clips.append(clip)

    project.updated_at = datetime.now(timezone.utc)
    await db.commit()
    for c in created_clips:
        await db.refresh(c)

    return {
        "character_anchors": storyboard.get("character_anchors", []),
        "visual_style": storyboard.get("visual_style", ""),
        "story_so_far": storyboard.get("story_so_far", ""),
        "clips": [ClipResponse.model_validate(c) for c in created_clips],
    }
