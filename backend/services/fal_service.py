"""
fal.ai service — wraps Seedance 2.0 Fast image-to-video generation.
Supports both fire-and-forget (submit) and polling (status check).
"""

import os
import asyncio
import logging
from typing import Optional, Callable, AsyncIterator

import fal_client

from config import settings

logger = logging.getLogger(__name__)

FAL_MODEL = "bytedance/seedance-2.0/fast/image-to-video"


def _configure_fal():
    """Inject FAL_KEY into environment so fal_client picks it up."""
    if settings.fal_key:
        os.environ["FAL_KEY"] = settings.fal_key


_configure_fal()


class FalJobResult:
    def __init__(self, video_url: str, seed: int, request_id: str):
        self.video_url = video_url
        self.seed = seed
        self.request_id = request_id


async def submit_clip(
    prompt: str,
    image_url: str,
    end_image_url: Optional[str] = None,
    resolution: str = "720p",
    duration: str = "auto",
    aspect_ratio: str = "auto",
    generate_audio: bool = True,
    seed: Optional[int] = None,
) -> str:
    """
    Submit a generation job to fal.ai and return the request_id immediately.
    Does NOT wait for completion. Use poll_clip() to check status.
    """
    args: dict = {
        "prompt": prompt,
        "image_url": image_url,
        "resolution": resolution,
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "generate_audio": generate_audio,
    }
    if end_image_url:
        args["end_image_url"] = end_image_url
    if seed is not None:
        args["seed"] = seed

    handler = await fal_client.submit_async(FAL_MODEL, arguments=args)
    logger.info(f"Submitted fal job: {handler.request_id}")
    return handler.request_id


async def poll_clip(request_id: str) -> Optional[FalJobResult]:
    """
    Check the status of a submitted job.
    Returns FalJobResult if complete, None if still running, raises on error.
    """
    status = await fal_client.status_async(FAL_MODEL, request_id, with_logs=False)

    if isinstance(status, fal_client.Queued):
        return None
    elif isinstance(status, fal_client.InProgress):
        return None
    elif isinstance(status, fal_client.Completed):
        result = await fal_client.result_async(FAL_MODEL, request_id)
        return FalJobResult(
            video_url=result["video"]["url"],
            seed=result["seed"],
            request_id=request_id,
        )
    else:
        raise RuntimeError(f"Unexpected fal status type: {type(status)}")


async def run_clip_sync(
    prompt: str,
    image_url: str,
    end_image_url: Optional[str] = None,
    resolution: str = "720p",
    duration: str = "auto",
    aspect_ratio: str = "auto",
    generate_audio: bool = True,
    seed: Optional[int] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> FalJobResult:
    """
    Submit and wait for completion synchronously (async-friendly).
    Use this for sequential rendering where you want to block until done.
    """
    args: dict = {
        "prompt": prompt,
        "image_url": image_url,
        "resolution": resolution,
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "generate_audio": generate_audio,
    }
    if end_image_url:
        args["end_image_url"] = end_image_url
    if seed is not None:
        args["seed"] = seed

    def _on_queue_update(update):
        if isinstance(update, fal_client.InProgress) and on_log:
            for log in update.logs:
                on_log(log["message"])

    result = await asyncio.to_thread(
        fal_client.subscribe,
        FAL_MODEL,
        arguments=args,
        with_logs=True,
        on_queue_update=_on_queue_update,
    )

    return FalJobResult(
        video_url=result["video"]["url"],
        seed=result["seed"],
        request_id="sync",
    )


async def upload_image(file_path: str) -> str:
    """Upload a local image file to fal storage and return its public URL."""
    url = await asyncio.to_thread(fal_client.upload_file, file_path)
    logger.info(f"Uploaded image to fal storage: {url}")
    return url
