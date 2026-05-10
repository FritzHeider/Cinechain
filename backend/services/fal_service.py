"""
fal.ai service — wraps all Seedance 2.0 model variants.
Supports image-to-video (i2v), text-to-video (t2v), and reference-to-video (ref)
in both Fast and Pro tiers.
"""

import os
import asyncio
import logging
from typing import Optional, Callable

import fal_client

from config import settings

logger = logging.getLogger(__name__)

SEEDANCE_MODELS = {
    "fast-i2v": "bytedance/seedance-2.0/fast/image-to-video",
    "pro-i2v":  "bytedance/seedance-2.0/image-to-video",
    "fast-t2v": "bytedance/seedance-2.0/fast/text-to-video",
    "pro-t2v":  "bytedance/seedance-2.0/text-to-video",
    "fast-ref": "bytedance/seedance-2.0/fast/reference-to-video",
    "pro-ref":  "bytedance/seedance-2.0/reference-to-video",
}
DEFAULT_MODEL = "fast-i2v"

_I2V = {"fast-i2v", "pro-i2v"}
_T2V = {"fast-t2v", "pro-t2v"}
_REF = {"fast-ref", "pro-ref"}


def _configure_fal():
    if settings.fal_key:
        os.environ["FAL_KEY"] = settings.fal_key


_configure_fal()


def _fal_model(key: str) -> str:
    return SEEDANCE_MODELS.get(key, SEEDANCE_MODELS[DEFAULT_MODEL])


def _model_type(key: str) -> str:
    if key in _T2V:
        return "t2v"
    if key in _REF:
        return "ref"
    return "i2v"


def _build_args(
    model_key: str,
    prompt: str,
    image_url: Optional[str] = None,
    end_image_url: Optional[str] = None,
    reference_image_urls: Optional[list] = None,
    reference_video_urls: Optional[list] = None,
    reference_audio_urls: Optional[list] = None,
    resolution: str = "720p",
    duration: str = "auto",
    aspect_ratio: str = "auto",
    generate_audio: bool = True,
    seed: Optional[int] = None,
) -> dict:
    mt = _model_type(model_key)
    args: dict = {
        "prompt": prompt,
        "resolution": resolution,
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "generate_audio": generate_audio,
    }
    if mt == "i2v":
        if image_url:
            args["image_url"] = image_url
        if end_image_url:
            args["end_image_url"] = end_image_url
    elif mt == "ref":
        if reference_image_urls:
            args["image_urls"] = reference_image_urls
        if reference_video_urls:
            args["video_urls"] = reference_video_urls
        if reference_audio_urls:
            args["audio_urls"] = reference_audio_urls
    if seed is not None:
        args["seed"] = seed
    return args


class FalJobResult:
    def __init__(self, video_url: str, seed: int, request_id: str):
        self.video_url = video_url
        self.seed = seed
        self.request_id = request_id


async def submit_clip(
    model_key: str = DEFAULT_MODEL,
    prompt: str = "",
    image_url: Optional[str] = None,
    end_image_url: Optional[str] = None,
    reference_image_urls: Optional[list] = None,
    reference_video_urls: Optional[list] = None,
    reference_audio_urls: Optional[list] = None,
    resolution: str = "720p",
    duration: str = "auto",
    aspect_ratio: str = "auto",
    generate_audio: bool = True,
    seed: Optional[int] = None,
) -> str:
    """Submit a generation job and return request_id immediately (non-blocking)."""
    args = _build_args(
        model_key, prompt, image_url, end_image_url,
        reference_image_urls, reference_video_urls, reference_audio_urls,
        resolution, duration, aspect_ratio, generate_audio, seed,
    )
    handler = await fal_client.submit_async(_fal_model(model_key), arguments=args)
    logger.info(f"Submitted fal job {handler.request_id} ({model_key})")
    return handler.request_id


async def poll_clip(request_id: str, model_key: str = DEFAULT_MODEL) -> Optional[FalJobResult]:
    """Check job status. Returns FalJobResult if complete, None if still running."""
    fal_model = _fal_model(model_key)
    status = await fal_client.status_async(fal_model, request_id, with_logs=False)

    if isinstance(status, (fal_client.Queued, fal_client.InProgress)):
        return None
    elif isinstance(status, fal_client.Completed):
        result = await fal_client.result_async(fal_model, request_id)
        return FalJobResult(
            video_url=result["video"]["url"],
            seed=result.get("seed", 0),
            request_id=request_id,
        )
    else:
        raise RuntimeError(f"Unexpected fal status type: {type(status)}")


async def run_clip_sync(
    model_key: str = DEFAULT_MODEL,
    prompt: str = "",
    image_url: Optional[str] = None,
    end_image_url: Optional[str] = None,
    reference_image_urls: Optional[list] = None,
    reference_video_urls: Optional[list] = None,
    reference_audio_urls: Optional[list] = None,
    resolution: str = "720p",
    duration: str = "auto",
    aspect_ratio: str = "auto",
    generate_audio: bool = True,
    seed: Optional[int] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> FalJobResult:
    """Submit and block until completion (async-friendly via thread)."""
    args = _build_args(
        model_key, prompt, image_url, end_image_url,
        reference_image_urls, reference_video_urls, reference_audio_urls,
        resolution, duration, aspect_ratio, generate_audio, seed,
    )

    def _on_queue_update(update):
        if isinstance(update, fal_client.InProgress) and on_log:
            for log in update.logs:
                on_log(log["message"])

    result = await asyncio.to_thread(
        fal_client.subscribe,
        _fal_model(model_key),
        arguments=args,
        with_logs=True,
        on_queue_update=_on_queue_update,
    )

    return FalJobResult(
        video_url=result["video"]["url"],
        seed=result.get("seed", 0),
        request_id="sync",
    )


async def upload_image(file_path: str) -> str:
    """Upload a local file to fal storage and return its public URL."""
    url = await asyncio.to_thread(fal_client.upload_file, file_path)
    logger.info(f"Uploaded to fal storage: {url}")
    return url
