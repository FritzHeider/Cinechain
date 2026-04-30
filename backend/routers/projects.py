from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone

from database import get_db, Project, Clip
from models import (
    ProjectCreate, ProjectUpdate, ProjectResponse, ProjectSummary,
    ClipCreate, ClipUpdate, ClipResponse,
)
from services.stitch_service import invalidate_norm_cache

router = APIRouter(prefix="/projects", tags=["projects"])


# ─── Projects ─────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ProjectSummary])
async def list_projects(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Project).order_by(Project.updated_at.desc())
    )
    projects = result.scalars().all()
    summaries = []
    for p in projects:
        clip_result = await db.execute(select(Clip).where(Clip.project_id == p.id))
        clip_count = len(clip_result.scalars().all())
        summaries.append(ProjectSummary(
            id=p.id,
            name=p.name,
            description=p.description,
            status=p.status,
            final_video_url=p.final_video_url,
            clip_count=clip_count,
            created_at=p.created_at,
            updated_at=p.updated_at,
        ))
    return summaries


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(data: ProjectCreate, db: AsyncSession = Depends(get_db)):
    project = Project(name=data.name, description=data.description)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return await _get_project_with_clips(project.id, db)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: int, db: AsyncSession = Depends(get_db)):
    return await _get_project_with_clips(project_id, db)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: int, data: ProjectUpdate, db: AsyncSession = Depends(get_db)):
    project = await _require_project(project_id, db)
    if data.name is not None:
        project.name = data.name
    if data.description is not None:
        project.description = data.description
    project.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return await _get_project_with_clips(project_id, db)


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: int, db: AsyncSession = Depends(get_db)):
    project = await _require_project(project_id, db)
    await db.delete(project)
    await db.commit()


# ─── Clips ────────────────────────────────────────────────────────────────────

@router.post("/{project_id}/clips", response_model=ClipResponse, status_code=201)
async def add_clip(project_id: int, data: ClipCreate, db: AsyncSession = Depends(get_db)):
    await _require_project(project_id, db)
    clip = Clip(project_id=project_id, **data.model_dump())
    db.add(clip)
    await db.commit()
    await db.refresh(clip)
    return clip


@router.get("/{project_id}/clips", response_model=list[ClipResponse])
async def list_clips(project_id: int, db: AsyncSession = Depends(get_db)):
    await _require_project(project_id, db)
    result = await db.execute(
        select(Clip).where(Clip.project_id == project_id).order_by(Clip.order)
    )
    return result.scalars().all()


@router.patch("/{project_id}/clips/{clip_id}", response_model=ClipResponse)
async def update_clip(project_id: int, clip_id: int, data: ClipUpdate, db: AsyncSession = Depends(get_db)):
    clip = await _require_clip(project_id, clip_id, db)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(clip, field, value)
    # Reset status if prompt/image changes
    if data.prompt is not None or data.image_url is not None:
        clip.status = "pending"
        clip.video_url = None
        clip.fal_request_id = None
        clip.error_message = None
        invalidate_norm_cache(clip.id)
    clip.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(clip)
    return clip


@router.delete("/{project_id}/clips/{clip_id}", status_code=204)
async def delete_clip(project_id: int, clip_id: int, db: AsyncSession = Depends(get_db)):
    clip = await _require_clip(project_id, clip_id, db)
    await db.delete(clip)
    await db.commit()


@router.post("/{project_id}/clips/reorder", response_model=list[ClipResponse])
async def reorder_clips(project_id: int, clip_ids: list[int], db: AsyncSession = Depends(get_db)):
    """Reorder clips by providing an ordered list of clip IDs."""
    await _require_project(project_id, db)
    for i, clip_id in enumerate(clip_ids):
        clip = await _require_clip(project_id, clip_id, db)
        clip.order = i
        clip.updated_at = datetime.now(timezone.utc)
    await db.commit()
    result = await db.execute(
        select(Clip).where(Clip.project_id == project_id).order_by(Clip.order)
    )
    return result.scalars().all()


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _require_project(project_id: int, db: AsyncSession) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return project


async def _require_clip(project_id: int, clip_id: int, db: AsyncSession) -> Clip:
    result = await db.execute(
        select(Clip).where(Clip.id == clip_id, Clip.project_id == project_id)
    )
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail=f"Clip {clip_id} not found in project {project_id}")
    return clip


async def _get_project_with_clips(project_id: int, db: AsyncSession) -> ProjectResponse:
    result = await db.execute(
        select(Project)
        .options(selectinload(Project.clips))
        .where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return project
