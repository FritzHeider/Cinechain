"""
Render router: orchestrates clip generation via fal.ai and final video stitching.

Endpoints:
  POST /projects/{id}/render                    kick off rendering (sequential or parallel)
  GET  /projects/{id}/render/status             poll render progress
  GET  /projects/{id}/render/stream             SSE stream of render events
  POST /projects/{id}/render/stitch             manually trigger stitching
  POST /projects/{id}/clips/{cid}/generate      generate a single clip
  GET  /projects/{id}/clips/{cid}/poll          poll a single clip's fal job
  POST /projects/{id}/clips/{cid}/use-as-next   extract last frame and set as next clip's start
  GET  /projects/{id}/download                  download final stitched video
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database import get_db, Project, Clip
from models import RenderRequest, RenderStatusResponse, ClipResponse
from services import fal_service, stitch_service
from services.stitch_service import invalidate_norm_cache
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["render"])

# In-memory SSE event queues keyed by project_id
_sse_queues: dict[int, list[asyncio.Queue]] = {}
_sse_counters: dict[int, int] = {}  # monotonic event ID per project


def _emit(project_id: int, event: dict):
    """Push an event (with a monotonic id) to all SSE listeners for this project."""
    _sse_counters[project_id] = _sse_counters.get(project_id, 0) + 1
    event = {"id": _sse_counters[project_id], **event}
    for q in _sse_queues.get(project_id, []):
        q.put_nowait(event)


# ─── Start render ─────────────────────────────────────────────────────────────

@router.post("/{project_id}/render")
async def start_render(
    project_id: int,
    req: RenderRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    project = await _require_project(project_id, db)

    result = await db.execute(
        select(Clip).where(Clip.project_id == project_id).order_by(Clip.order)
    )
    clips = result.scalars().all()

    if req.clip_ids:
        clips = [c for c in clips if c.id in req.clip_ids]

    if not clips:
        raise HTTPException(status_code=400, detail="No clips to render.")

    project.status = "rendering"
    project.updated_at = datetime.now(timezone.utc)

    for clip in clips:
        if clip.is_passthrough:
            # Original uploaded video — preserve its video_url, just ensure status is complete
            clip.status = "complete"
            continue
        clip.status = "pending"
        clip.video_url = None
        clip.fal_request_id = None
        clip.error_message = None
        # Invalidate normalized cache so stitch re-normalizes fresh clips
        invalidate_norm_cache(clip.id)

    await db.commit()

    # Only render non-passthrough clips
    draft = req.draft
    clip_ids = [c.id for c in clips if not c.is_passthrough]

    if req.parallel:
        background_tasks.add_task(
            _render_parallel, project_id, clip_ids, req.stitch, draft,
            req.crossfade, req.crossfade_duration, req.max_retries,
        )
    else:
        background_tasks.add_task(
            _render_sequential, project_id, clip_ids, req.stitch, draft,
            req.crossfade, req.crossfade_duration, req.max_retries, req.auto_chain,
        )

    return {
        "message": f"Rendering started for {len(clips)} clips",
        "clip_ids": clip_ids,
        "mode": "parallel" if req.parallel else "sequential",
        "draft": draft,
    }


# ─── Render status ────────────────────────────────────────────────────────────

@router.get("/{project_id}/render/status", response_model=RenderStatusResponse)
async def render_status(project_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Project).options(selectinload(Project.clips)).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    clips = sorted(project.clips, key=lambda c: c.order)
    counts = {"pending": 0, "queued": 0, "generating": 0, "complete": 0, "error": 0}
    for clip in clips:
        counts[clip.status] = counts.get(clip.status, 0) + 1

    return RenderStatusResponse(
        project_id=project_id,
        project_status=project.status,
        final_video_url=project.final_video_url,
        clips=clips,
        total=len(clips),
        **counts,
    )


# ─── SSE stream ───────────────────────────────────────────────────────────────

@router.get("/{project_id}/render/stream")
async def render_stream(project_id: int):
    """
    Server-Sent Events stream of render progress for a project.
    The client receives JSON events: {type, clip_id?, status?, message?}
    """
    queue: asyncio.Queue = asyncio.Queue()
    _sse_queues.setdefault(project_id, []).append(queue)

    async def generator():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    event_id = event.get("id", "")
                    yield f"id: {event_id}\ndata: {json.dumps(event)}\n\n"
                    if event.get("type") == "done":
                        break
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            try:
                _sse_queues.get(project_id, []).remove(queue)
            except ValueError:
                pass

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── Manual stitch ────────────────────────────────────────────────────────────

@router.post("/{project_id}/render/stitch")
async def manual_stitch(
    project_id: int,
    crossfade: bool = True,
    crossfade_duration: float = 0.5,
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Clip).where(Clip.project_id == project_id).order_by(Clip.order)
    )
    clips = result.scalars().all()
    incomplete = [c for c in clips if not c.video_url]
    if incomplete:
        raise HTTPException(
            status_code=400,
            detail=f"{len(incomplete)} clip(s) don't have videos yet: {[c.id for c in incomplete]}",
        )

    background_tasks.add_task(
        _stitch_project, project_id,
        crossfade=crossfade, crossfade_duration=crossfade_duration,
    )
    return {"message": "Stitching started"}


# ─── Single clip generation ───────────────────────────────────────────────────

@router.post("/{project_id}/clips/{clip_id}/generate", response_model=ClipResponse)
async def generate_clip(project_id: int, clip_id: int, db: AsyncSession = Depends(get_db)):
    clip = await _require_clip(project_id, clip_id, db)

    if clip.is_passthrough:
        raise HTTPException(status_code=400, detail="Cannot regenerate a passthrough clip (original uploaded video).")

    request_id = await fal_service.submit_clip(
        prompt=clip.prompt,
        image_url=clip.image_url,
        end_image_url=clip.end_image_url,
        resolution=clip.resolution,
        duration=clip.duration,
        aspect_ratio=clip.aspect_ratio,
        generate_audio=clip.generate_audio,
        seed=clip.seed,
    )

    clip.fal_request_id = request_id
    clip.status = "queued"
    clip.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(clip)
    return clip


@router.get("/{project_id}/clips/{clip_id}/poll", response_model=ClipResponse)
async def poll_clip(project_id: int, clip_id: int, db: AsyncSession = Depends(get_db)):
    clip = await _require_clip(project_id, clip_id, db)

    if not clip.fal_request_id:
        raise HTTPException(status_code=400, detail="Clip has not been submitted yet.")
    if clip.status == "complete":
        return clip

    result = await fal_service.poll_clip(clip.fal_request_id)
    if result:
        clip.status = "complete"
        clip.video_url = result.video_url
        clip.video_seed = result.seed
        clip.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(clip)
    else:
        clip.status = "generating"
        await db.commit()
        await db.refresh(clip)

    return clip


# ─── Extract last frame → use as next clip's start ────────────────────────────

@router.post("/{project_id}/clips/{clip_id}/use-as-next", response_model=ClipResponse)
async def use_last_frame_as_next(
    project_id: int,
    clip_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Extract the last frame of clip_id's video and set it as the image_url
    of the next clip in sequence. Returns the updated next clip.
    """
    # Get current clip
    clip = await _require_clip(project_id, clip_id, db)
    if not clip.video_url:
        raise HTTPException(status_code=400, detail="Clip has no video yet.")

    # Find the next clip
    result = await db.execute(
        select(Clip)
        .where(Clip.project_id == project_id, Clip.order > clip.order)
        .order_by(Clip.order)
    )
    next_clip = result.scalars().first()
    if not next_clip:
        raise HTTPException(status_code=404, detail="No next clip to update.")

    # Download current clip video to a temp location and extract last frame
    frame_filename = f"frame_{clip_id}_{uuid.uuid4().hex[:8]}.jpg"
    frame_path = settings.upload_dir / frame_filename
    tmp_video = settings.upload_dir / f"tmp_vid_{uuid.uuid4().hex[:8]}.mp4"

    try:
        await stitch_service.download_video(clip.video_url, tmp_video)
        await stitch_service.extract_last_frame(tmp_video, frame_path)
    finally:
        if tmp_video.exists():
            tmp_video.unlink()

    # Upload the frame to fal storage for a public URL
    public_url = await fal_service.upload_image(str(frame_path))

    # Update next clip
    next_clip.image_url = public_url
    next_clip.status = "pending"
    next_clip.video_url = None
    next_clip.fal_request_id = None
    next_clip.error_message = None
    next_clip.updated_at = datetime.now(timezone.utc)
    invalidate_norm_cache(next_clip.id)
    await db.commit()
    await db.refresh(next_clip)
    return next_clip


# ─── Download final video ─────────────────────────────────────────────────────

@router.get("/{project_id}/download")
async def download_final(project_id: int, db: AsyncSession = Depends(get_db)):
    project = await _require_project(project_id, db)
    if not project.final_video_url:
        raise HTTPException(status_code=404, detail="Final video not yet available.")
    file_path = Path(project.final_video_url)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Final video file not found on disk.")
    return FileResponse(
        path=str(file_path),
        media_type="video/mp4",
        filename=file_path.name,
    )


# ─── Background tasks ─────────────────────────────────────────────────────────

async def _run_clip_with_retry(clip_id: int, draft: bool, max_retries: int, project_id: int) -> bool:
    """
    Run a single clip synchronously with retry logic.
    Returns True on success, False on permanent failure.
    """
    from database import AsyncSessionLocal
    delay = 2.0
    for attempt in range(1, max_retries + 1):
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Clip).where(Clip.id == clip_id))
            clip = result.scalar_one_or_none()
            if not clip:
                return False

            try:
                resolution = "480p" if draft else clip.resolution
                _emit(project_id, {"type": "clip_start", "clip_id": clip_id, "attempt": attempt})
                job_result = await fal_service.run_clip_sync(
                    prompt=clip.prompt,
                    image_url=clip.image_url,
                    end_image_url=clip.end_image_url,
                    resolution=resolution,
                    duration=clip.duration,
                    aspect_ratio=clip.aspect_ratio,
                    generate_audio=clip.generate_audio,
                    seed=clip.seed,
                    on_log=lambda msg: logger.info(f"[fal clip {clip_id}] {msg}"),
                )
                clip.status = "complete"
                clip.video_url = job_result.video_url
                clip.video_seed = job_result.seed
                clip.fal_request_id = job_result.request_id
                clip.updated_at = datetime.now(timezone.utc)
                await db.commit()
                _emit(project_id, {"type": "clip_complete", "clip_id": clip_id})
                return True

            except Exception as e:
                logger.warning(f"[render] Clip {clip_id} attempt {attempt}/{max_retries} failed: {e}")
                if attempt == max_retries:
                    clip.status = "error"
                    clip.error_message = str(e)
                    clip.updated_at = datetime.now(timezone.utc)
                    await db.commit()
                    _emit(project_id, {"type": "clip_error", "clip_id": clip_id, "message": str(e)})
                    return False
                else:
                    clip.status = "pending"
                    clip.updated_at = datetime.now(timezone.utc)
                    await db.commit()

        await asyncio.sleep(delay)
        delay *= 2  # exponential backoff

    return False


async def _render_sequential(
    project_id: int, clip_ids: list[int], stitch: bool,
    draft: bool, crossfade: bool, crossfade_duration: float, max_retries: int,
    auto_chain: bool = False,
):
    from database import AsyncSessionLocal
    from services.stitch_service import download_video, extract_last_frame as _elf
    import uuid as _uuid

    _emit(project_id, {"type": "render_start", "mode": "sequential"})
    chain_broken = False  # set True when a clip fails mid-chain

    for i, clip_id in enumerate(clip_ids):
        if chain_broken:
            # Mark remaining clips as errored rather than submitting with empty image_url
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Clip).where(Clip.id == clip_id))
                clip = result.scalar_one_or_none()
                if clip:
                    clip.status = "error"
                    clip.error_message = "Skipped: earlier clip in auto-chain failed"
                    clip.updated_at = datetime.now(timezone.utc)
                    await db.commit()
            _emit(project_id, {"type": "clip_error", "clip_id": clip_id, "message": "Skipped: earlier clip in auto-chain failed"})
            continue

        success = await _run_clip_with_retry(clip_id, draft, max_retries, project_id)

        if not success and auto_chain:
            chain_broken = True
            continue

        # Auto-chain: extract last frame and set as start of next clip
        if auto_chain and success and i + 1 < len(clip_ids):
            next_clip_id = clip_ids[i + 1]
            try:
                async with AsyncSessionLocal() as db:
                    result = await db.execute(select(Clip).where(Clip.id == clip_id))
                    clip = result.scalar_one_or_none()
                    result2 = await db.execute(select(Clip).where(Clip.id == next_clip_id))
                    next_clip = result2.scalar_one_or_none()

                    if clip and clip.video_url and next_clip:
                        tmp_video = settings.upload_dir / f"tmp_{_uuid.uuid4().hex[:8]}.mp4"
                        frame_path = settings.upload_dir / f"chain_{_uuid.uuid4().hex[:8]}.jpg"
                        try:
                            await download_video(clip.video_url, tmp_video)
                            await _elf(tmp_video, frame_path)
                            public_url = await fal_service.upload_image(str(frame_path))
                            next_clip.image_url = public_url
                            next_clip.updated_at = datetime.now(timezone.utc)
                            await db.commit()
                            logger.info(f"[auto_chain] Chained clip {clip_id} → {next_clip_id}")
                            _emit(project_id, {"type": "chain_complete", "from_clip": clip_id, "to_clip": next_clip_id})
                        finally:
                            tmp_video.unlink(missing_ok=True)
                            frame_path.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"[auto_chain] Failed to chain clip {clip_id} → {next_clip_id}: {e}")
                chain_broken = True

    if stitch:
        await _stitch_project(project_id, crossfade=crossfade, crossfade_duration=crossfade_duration)
    else:
        _emit(project_id, {"type": "done"})


async def _render_parallel(
    project_id: int, clip_ids: list[int], stitch: bool,
    draft: bool, crossfade: bool, crossfade_duration: float, max_retries: int,
):
    from database import AsyncSessionLocal
    _emit(project_id, {"type": "render_start", "mode": "parallel"})

    # Submit all
    async with AsyncSessionLocal() as db:
        for clip_id in clip_ids:
            result = await db.execute(select(Clip).where(Clip.id == clip_id))
            clip = result.scalar_one_or_none()
            if not clip:
                continue
            try:
                resolution = "480p" if draft else clip.resolution
                request_id = await fal_service.submit_clip(
                    prompt=clip.prompt,
                    image_url=clip.image_url,
                    end_image_url=clip.end_image_url,
                    resolution=resolution,
                    duration=clip.duration,
                    aspect_ratio=clip.aspect_ratio,
                    generate_audio=clip.generate_audio,
                    seed=clip.seed,
                )
                clip.fal_request_id = request_id
                clip.status = "queued"
                _emit(project_id, {"type": "clip_queued", "clip_id": clip_id})
            except Exception as e:
                clip.status = "error"
                clip.error_message = str(e)
                _emit(project_id, {"type": "clip_error", "clip_id": clip_id, "message": str(e)})
            clip.updated_at = datetime.now(timezone.utc)
        await db.commit()

    # Poll until all done, with per-clip retry on error
    pending = set(clip_ids)
    error_counts: dict[int, int] = {cid: 0 for cid in clip_ids}

    while pending:
        await asyncio.sleep(5)
        async with AsyncSessionLocal() as db:
            done = set()
            for clip_id in list(pending):
                result = await db.execute(select(Clip).where(Clip.id == clip_id))
                clip = result.scalar_one_or_none()
                if not clip or not clip.fal_request_id:
                    done.add(clip_id)
                    continue
                try:
                    job_result = await fal_service.poll_clip(clip.fal_request_id)
                    if job_result:
                        clip.status = "complete"
                        clip.video_url = job_result.video_url
                        clip.video_seed = job_result.seed
                        clip.updated_at = datetime.now(timezone.utc)
                        done.add(clip_id)
                        _emit(project_id, {"type": "clip_complete", "clip_id": clip_id})
                    else:
                        clip.status = "generating"
                        clip.updated_at = datetime.now(timezone.utc)
                        _emit(project_id, {"type": "clip_status", "clip_id": clip_id, "status": "generating"})
                except Exception as e:
                    error_counts[clip_id] = error_counts.get(clip_id, 0) + 1
                    if error_counts[clip_id] >= max_retries:
                        clip.status = "error"
                        clip.error_message = str(e)
                        clip.updated_at = datetime.now(timezone.utc)
                        done.add(clip_id)
                        _emit(project_id, {"type": "clip_error", "clip_id": clip_id, "message": str(e)})
                    else:
                        logger.warning(f"[parallel] Clip {clip_id} poll error (attempt {error_counts[clip_id]}): {e}")
            await db.commit()
            pending -= done

    if stitch:
        await _stitch_project(project_id, crossfade=crossfade, crossfade_duration=crossfade_duration)
    else:
        _emit(project_id, {"type": "done"})


async def _stitch_project(project_id: int, crossfade: bool = True, crossfade_duration: float = 0.5):
    from database import AsyncSessionLocal
    _emit(project_id, {"type": "stitch_start"})

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Clip).where(Clip.project_id == project_id).order_by(Clip.order)
        )
        clips = result.scalars().all()

        clip_dicts = [
            {
                "id": c.id,
                "video_url": c.video_url,
                "resolution": c.resolution,
                "transition_type": c.transition_type or "fade",
            }
            for c in clips if c.video_url
        ]

        project_result = await db.execute(select(Project).where(Project.id == project_id))
        project = project_result.scalar_one_or_none()

        if not clip_dicts:
            if project:
                project.status = "error"
                project.updated_at = datetime.now(timezone.utc)
                await db.commit()
            _emit(project_id, {"type": "done", "error": "No clips with video"})
            return

        resolution = clips[0].resolution if clips else "720p"

        try:
            final_path = await stitch_service.stitch_clips(
                clips=clip_dicts,
                project_id=project_id,
                resolution=resolution,
                crossfade=crossfade,
                crossfade_duration=crossfade_duration,
            )
            if project:
                project.status = "complete"
                project.final_video_url = final_path
                project.updated_at = datetime.now(timezone.utc)
            _emit(project_id, {"type": "stitch_complete", "final_video_url": final_path})
        except Exception as e:
            logger.error(f"[stitch] Project {project_id} failed: {e}")
            if project:
                project.status = "error"
                project.updated_at = datetime.now(timezone.utc)
            _emit(project_id, {"type": "done", "error": str(e)})

        await db.commit()
    _emit(project_id, {"type": "done"})


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _require_project(project_id: int, db: AsyncSession) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _require_clip(project_id: int, clip_id: int, db: AsyncSession) -> Clip:
    result = await db.execute(
        select(Clip).where(Clip.id == clip_id, Clip.project_id == project_id)
    )
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    return clip
