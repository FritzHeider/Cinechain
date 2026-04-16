"""
Stitch service: downloads generated clip videos and assembles them into
a final cinematic video using FFmpeg concat demuxer.

Handles:
- Downloading clips from fal CDN URLs
- Normalizing codec/resolution/fps across clips
- Concat with optional crossfade transitions
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


def _check_ffmpeg():
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg not found. Install it with: brew install ffmpeg (macOS) or apt install ffmpeg (Linux)"
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
    Re-encode a clip to a consistent format:
    - H.264 video, AAC audio
    - 24 fps
    - Target resolution (720p = 1280x720, 480p = 854x480)
    - yuv420p pixel format for maximum compatibility
    """
    _check_ffmpeg()

    scale = "1280:720" if resolution == "720p" else "854:480"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(src),
        "-vf", f"scale={scale}:force_original_aspect_ratio=decrease,pad={scale}:(ow-iw)/2:(oh-ih)/2,fps=24",
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


async def crossfade_two_clips(clip_a: Path, clip_b: Path, dst: Path, fade_duration: float = 0.5) -> None:
    """
    Apply a crossfade transition between two clips using FFmpeg xfade filter.
    Both clips must be normalized first.
    """
    _check_ffmpeg()

    # Get duration of clip_a to calculate crossfade offset
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(clip_a),
    ]
    proc = await asyncio.create_subprocess_exec(
        *probe_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    duration_a = float(stdout.decode().strip())
    offset = max(0.0, duration_a - fade_duration)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(clip_a),
        "-i", str(clip_b),
        "-filter_complex",
        (
            f"[0:v][1:v]xfade=transition=fade:duration={fade_duration}:offset={offset}[vout];"
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
    """
    Simple concat (no transition) using FFmpeg concat demuxer.
    All clips must share the same codec/resolution/fps.
    """
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


async def stitch_clips(
    video_urls: list[str],
    project_id: int,
    resolution: str = "720p",
    crossfade: bool = True,
    crossfade_duration: float = 0.5,
) -> str:
    """
    Full pipeline:
    1. Download all clip videos
    2. Normalize to consistent format
    3. Apply crossfade transitions (optional)
    4. Concat into final video
    5. Return local file path of final video

    Returns path to the final stitched video file.
    """
    _check_ffmpeg()

    if not video_urls:
        raise ValueError("No video URLs provided for stitching.")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Step 1: Download
        logger.info(f"[stitch] Downloading {len(video_urls)} clips...")
        raw_paths = []
        for i, url in enumerate(video_urls):
            raw = tmp / f"raw_{i:03d}.mp4"
            await download_video(url, raw)
            raw_paths.append(raw)

        # Step 2: Normalize
        logger.info("[stitch] Normalizing clips...")
        norm_paths = []
        for i, raw in enumerate(raw_paths):
            norm = tmp / f"norm_{i:03d}.mp4"
            await normalize_clip(raw, norm, resolution=resolution)
            norm_paths.append(norm)

        # Step 3 & 4: Crossfade + concat
        output_filename = f"cinechain_project_{project_id}_{uuid.uuid4().hex[:8]}.mp4"
        final_output = settings.output_dir / output_filename

        if crossfade and len(norm_paths) > 1:
            logger.info("[stitch] Applying crossfade transitions...")
            # Chain crossfades: A+B → AB, AB+C → ABC, ...
            current = norm_paths[0]
            for i in range(1, len(norm_paths)):
                faded = tmp / f"faded_{i:03d}.mp4"
                await crossfade_two_clips(current, norm_paths[i], faded, fade_duration=crossfade_duration)
                current = faded
            shutil.copy2(str(current), str(final_output))
        else:
            logger.info("[stitch] Concatenating clips (no transitions)...")
            await concat_clips(norm_paths, final_output)

        logger.info(f"[stitch] Final video: {final_output}")
        return str(final_output)
