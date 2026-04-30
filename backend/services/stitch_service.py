"""
Stitch service: downloads generated clip videos and assembles them into
a final cinematic video using FFmpeg.

Handles:
- Downloading clips from fal CDN URLs
- Normalizing codec/resolution/fps/audio across clips (with loudnorm)
- Caching normalized clips on disk by clip ID to enable resume
- Per-clip transition types via FFmpeg xfade filter
- Outputting final MP4
"""

import asyncio
import logging
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

# Persistent cache dir for normalized clips — survives between stitch calls
NORM_CACHE_DIR = settings.output_dir / "norm_cache"
NORM_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _check_ffmpeg():
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg not found. Install with: brew install ffmpeg (macOS) or apt install ffmpeg (Linux)"
        )


async def download_video(url: str, dest: Path) -> None:
    """Stream-download a video URL to a local path."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    f.write(chunk)
    logger.info(f"Downloaded {url} → {dest}")


async def normalize_clip(src: Path, dst: Path, resolution: str = "720p") -> None:
    """
    Re-encode a clip to consistent format with audio normalization:
    - H.264 video, AAC audio
    - 24 fps, target resolution (720p = 1280x720, 480p = 854x480)
    - yuv420p pixel format
    - loudnorm audio filter for consistent volume levels
    """
    _check_ffmpeg()

    scale = "1280:720" if resolution == "720p" else "854:480"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(src),
        "-vf", f"scale={scale}:force_original_aspect_ratio=decrease,pad={scale}:(ow-iw)/2:(oh-ih)/2,fps=24",
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(dst),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg normalize failed:\n{stderr.decode()}")


async def extract_thumbnail(video_path: Path, output_path: Path, time: float = 0.5) -> None:
    """Extract a single frame from a video as a JPEG thumbnail."""
    _check_ffmpeg()
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(time),
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "3",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()


async def extract_last_frame(video_path: Path, output_path: Path) -> None:
    """Extract the very last frame of a video as a JPEG image."""
    _check_ffmpeg()
    cmd = [
        "ffmpeg", "-y",
        "-sseof", "-0.1",
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg last-frame extraction failed:\n{stderr.decode()}")


async def get_duration(video_path: Path) -> float:
    """Return video duration in seconds via ffprobe."""
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *probe_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return float(stdout.decode().strip())


async def crossfade_two_clips(
    clip_a: Path,
    clip_b: Path,
    dst: Path,
    fade_duration: float = 0.5,
    transition: str = "fade",
) -> None:
    """
    Apply an xfade transition between two clips.
    Both clips must be normalized first.
    Supports all FFmpeg xfade transition types.
    """
    _check_ffmpeg()

    duration_a = await get_duration(clip_a)
    offset = max(0.0, duration_a - fade_duration)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(clip_a),
        "-i", str(clip_b),
        "-filter_complex",
        (
            f"[0:v][1:v]xfade=transition={transition}:duration={fade_duration}:offset={offset}[vout];"
            f"[0:a][1:a]acrossfade=d={fade_duration}[aout]"
        ),
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(dst),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg xfade failed:\n{stderr.decode()}")


async def concat_clips(clip_paths: list[Path], output: Path) -> None:
    """Simple concat (no transitions) using FFmpeg concat demuxer."""
    _check_ffmpeg()

    list_file = output.parent / f"concat_{uuid.uuid4().hex}.txt"
    try:
        with open(list_file, "w") as f:
            for p in clip_paths:
                f.write(f"file '{p.resolve()}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            "-movflags", "+faststart",
            str(output),
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg concat failed:\n{stderr.decode()}")
    finally:
        if list_file.exists():
            list_file.unlink()


def _norm_cache_path(clip_id: int, resolution: str) -> Path:
    """Return the persistent cache path for a normalized clip."""
    return NORM_CACHE_DIR / f"clip_{clip_id}_{resolution}.mp4"


async def stitch_clips(
    clips: list[dict],  # list of {id, video_url, resolution, transition_type}
    project_id: int,
    resolution: str = "720p",
    crossfade: bool = True,
    crossfade_duration: float = 0.5,
) -> str:
    """
    Full pipeline:
    1. Download clips (skip if normalized cache exists)
    2. Normalize to consistent format with audio loudnorm (cached by clip ID)
    3. Apply per-clip xfade transitions (optional)
    4. Concat into final video
    5. Return local file path of final video
    """
    _check_ffmpeg()

    if not clips:
        raise ValueError("No clips provided for stitching.")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        norm_paths = []
        for i, clip in enumerate(clips):
            clip_id = clip["id"]
            url = clip["video_url"]

            cached = _norm_cache_path(clip_id, resolution)
            if cached.exists():
                logger.info(f"[stitch] Using cached normalized clip {clip_id}")
                norm_paths.append(cached)
                continue

            # Download
            raw = tmp / f"raw_{i:03d}.mp4"
            logger.info(f"[stitch] Downloading clip {clip_id}...")
            await download_video(url, raw)

            # Normalize into persistent cache
            logger.info(f"[stitch] Normalizing clip {clip_id}...")
            await normalize_clip(raw, cached, resolution=resolution)
            norm_paths.append(cached)

        output_filename = f"cinechain_project_{project_id}_{uuid.uuid4().hex[:8]}.mp4"
        final_output = settings.output_dir / output_filename

        if crossfade and len(norm_paths) > 1:
            logger.info("[stitch] Applying crossfade transitions...")
            current = norm_paths[0]
            for i in range(1, len(norm_paths)):
                transition = clips[i].get("transition_type", "fade")
                faded = tmp / f"faded_{i:03d}.mp4"
                await crossfade_two_clips(
                    current, norm_paths[i], faded,
                    fade_duration=crossfade_duration,
                    transition=transition,
                )
                current = faded
            shutil.copy2(str(current), str(final_output))
        else:
            logger.info("[stitch] Concatenating clips (no transitions)...")
            await concat_clips(norm_paths, final_output)

        logger.info(f"[stitch] Final video: {final_output}")
        return str(final_output)


def invalidate_norm_cache(clip_id: int) -> None:
    """Delete cached normalized files for a clip (call when clip video changes)."""
    for res in ("720p", "480p"):
        p = _norm_cache_path(clip_id, res)
        if p.exists():
            p.unlink()
            logger.info(f"Invalidated norm cache for clip {clip_id} ({res})")
