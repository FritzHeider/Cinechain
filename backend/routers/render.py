"""
Render router: orchestrates clip generation via fal.ai and final video stitching.

Endpoints:
  POST /projects/{id}/render        — kick off rendering (sequential or parallel)
  GET  /projects/{id}/render/status — poll render progress
  POST /projects/{id}/render/stitch — manually trigger stitching after all clips done
  POST /projects/{id}/clips/{cid}/generate — generate a single clip
  GET  /projects/{id}/clips/{cid}/poll     — poll a single clip's fal job
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database import get_db, Project, Clip
from models import RenderRequest, RenderStatusResponse, ClipResponse
from services import fal_service, stitch_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["render"])


# ─── Start render ─────────────────────────────────────────────────────────────

@router.post("/{project_id}/render")
async def start_render(
    project_id: int,
    req: RenderRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Start rendering clips. If parallel=True, all clips are submitted to fal.ai
    simultaneously and polled in the background. If False (default), clips are
    generated one at a time in order — each clip's end frame can feed into the
    next clip's start image.
    """
    project = await _require_project(project_id, db)

    # Determine which clips to render
    result = await db.execute(
        select(Clip)
        .where(Clip.project_id == project_id)
        .order_by(Clip.order)
    )
    clips = result.scalars().all()

    if req.clip_ids:
        clips = [c for c in clips if c.id in req.clip_ids]

    if not clips:
        raise HTTPException(status_code=400, detail="No clips to render.")

    # Mark project as rendering
    project.status = "rendering"
    project.updated_at = datetime.now(timezone.utc)

    # Reset target clips to pending
    for clip in clips:
        clip.status = "pending"
        clip.video_url = None
        clip.fal_request_id = None
        clip.error_message = None

    await db.commit()

    clip_ids = [c.id for c in clips]
    stitch = req.stitch

    if req.parallel:
        background_tasks.add_task(_render_parallel, project_id, clip_ids, stitch)
    else:
        background_tasks.add_task(_render_sequential, project_id, clip_ids, stitch)

    return {
        "message": f"Rendering started for {len(clips)} clips",
        "clip_ids": clip_ids,
        "mode": "parallel" if req.parallel else "sequential",
    }


# ─── Render status ────────────────────────────────────────────────────────────

@router.get("/{project_id}/render/status", response_model=RenderStatusResponse)
async def render_status(project_id: int, db: AsyncSession = Depends(get_db)):
    """Poll overall render progress for a project."""
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


# ─── Manual stitch ────────────────────────────────────────────────────────────

@router.post("/{project_id}/render/stitch")
async def manual_stitch(
    project_id: int,
    crossfade: bool = True,
    crossfade_duration: float = 0.5,
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger stitching once all clips have video_urls."""
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
        _stitch_project, project_id, crossfade=crossfade, crossfade_duration=crossfade_duration
    )
    return {"message": "Stitching started"}


# ─── Single clip generation ───────────────────────────────────────────────────

@router.post("/{project_id}/clips/{clip_id}/generate", response_model=ClipResponse)
async def generate_clip(project_id: int, clip_id: int, db: AsyncSession = Depends(get_db)):
    """Submit a single clip to fal.ai for generation. Returns immediately with request_id."""
    clip = await _require_clip(project_id, clip_id, db)

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
    """Check the fal.ai status of a single clip and update DB accordingly."""
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

async def _render_sequential(project_id: int, clip_ids: list[int], stitch: bool):
    """Generate clips one at a time, polling until each is done before starting the next."""
    from database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        for clip_id in clip_ids:
            result = await db.execute(select(Clip).where(Clip.id == clip_id))
            clip = result.scalar_one_or_none()
            if not clip:
                continue

            logger.info(f"[render] Starting clip {clip_id}...")
            clip.status = "generating"
            await db.commit()

            try:
                job_result = await fal_service.run_clip_sync(
                    prompt=clip.prompt,
                    image_url=clip.image_url,
                    end_image_url=clip.end_image_url,
                    resolution=clip.resolution,
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
            except Exception as e:
                logger.error(f"[render] Clip {clip_id} failed: {e}")
                clip.status = "error"
                clip.error_message = str(e)

            clip.updated_at = datetime.now(timezone.utc)
            await db.commit()

    if stitch:
        await _stitch_project(project_id)


async def _render_parallel(project_id: int, clip_ids: list[int], stitch: bool):
    """Submit all clips simultaneously, then poll until all are done."""
    from database import AsyncSessionLocal

    # Submit all
    async with AsyncSessionLocal() as db:
        for clip_id in clip_ids:
            result = await db.execute(select(Clip).where(Clip.id == clip_id))
            clip = result.scalar_one_or_none()
            if not clip:
                continue
            try:
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
            except Exception as e:
                clip.status = "error"
                clip.error_message = str(e)
            clip.updated_at = datetime.now(timezone.utc)
        await db.commit()

    # Poll until all complete
    pending = set(clip_ids)
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
                    else:
                        clip.status = "generating"
                        clip.updated_at = datetime.now(timezone.utc)
                except Exception as e:
                    clip.status = "error"
                    clip.error_message = str(e)
                    clip.updated_at = datetime.now(timezone.utc)
                    done.add(clip_id)
            await db.commit()
            pending -= done

    if stitch:
        await _stitch_project(project_id)


async def _stitch_project(project_id: int, crossfade: bool = True, crossfade_duration: float = 0.5):
    """Assemble all completed clip videos into a final cinematic video."""
    from database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Clip)
            .where(Clip.project_id == project_id)
            .order_by(Clip.order)
        )
        clips = result.scalars().all()
        video_urls = [c.video_url for c in clips if c.video_url]

        project_result = await db.execute(select(Project).where(Project.id == project_id))
        project = project_result.scalar_one_or_none()

        if not video_urls:
            if project:
                project.status = "error"
                project.updated_at = datetime.now(timezone.utc)
                await db.commit()
            return

        # Determine dominant resolution
        resolution = clips[0].resolution if clips else "720p"

        try:
            final_path = await stitch_service.stitch_clips(
                video_urls=video_urls,
                project_id=project_id,
                resolution=resolution,
                crossfade=crossfade,
                crossfade_duration=crossfade_duration,
            )
            if project:
                project.status = "complete"
                project.final_video_url = final_path
                project.updated_at = datetime.now(timezone.utc)
        except Exception as e:
            logger.error(f"[stitch] Project {project_id} failed: {e}")
            if project:
                project.status = "error"
                project.updated_at = datetime.now(timezone.utc)

        await db.commit()


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
