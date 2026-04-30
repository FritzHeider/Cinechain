"""
Extend service: analyzes an uploaded video with Claude vision and generates
a continuation storyboard — named scenes with character-anchored motion prompts.
"""

import asyncio
import base64
import json
import logging
import subprocess
import tempfile
from pathlib import Path

import anthropic

from config import settings

logger = logging.getLogger(__name__)

MASTER_PROMPT = """You are an award-winning cinematographer and screenwriter tasked with extending a movie short into a longer cinematic sequence.

Your job:
1. ANALYZE the provided video frames carefully — identify every character by precise visual description (hair color/length, clothing, distinguishing features), the setting, lighting mood, color palette, camera style, and narrative arc.
2. IDENTIFY character anchors — assign each recurring character a short anchor tag (CHAR_A, CHAR_B, etc.) and a concrete one-sentence visual description. These will be referenced in every scene prompt so the AI video generator maintains visual consistency.
3. WRITE continuation scenes — each scene must:
   - Follow naturally from the story/tone of the original
   - Reference characters by anchor tag + their visual description embedded in the prompt (e.g. "CHAR_A — the tall woman with short copper hair and a worn leather jacket — walks toward the camera")
   - Specify cinematic camera movement (dolly, pan, crane, handheld, etc.)
   - Specify lighting and mood
   - Be 1–3 vivid sentences that an AI video model can execute frame-by-frame

CRITICAL FOR CHARACTER CONTINUITY:
Each scene's prompt MUST embed the character's full visual description so the video model can recreate them from scratch with no prior context. Do not use pronouns alone — always anchor to appearance.

OUTPUT FORMAT — respond ONLY with valid JSON, no other text:
{
  "character_anchors": [
    {"tag": "CHAR_A", "description": "...one sentence visual description..."}
  ],
  "visual_style": "...brief description of the film's visual style, color grade, aspect ratio feel...",
  "story_so_far": "...1-2 sentences summarizing what happened in the original video...",
  "scenes": [
    {
      "name": "...",
      "story_beat": "...one sentence narrative description...",
      "prompt": "...full cinematic motion prompt with embedded character descriptions and camera direction..."
    }
  ]
}"""


def _run_ffprobe(video_path: str) -> float:
    """Return video duration in seconds."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", video_path,
        ],
        capture_output=True, text=True, timeout=30,
    )
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


def _extract_frame_at(video_path: str, timestamp: float, out_path: str):
    subprocess.run(
        [
            "ffmpeg", "-ss", str(timestamp), "-i", video_path,
            "-vframes", "1", "-q:v", "3", "-y", out_path,
        ],
        capture_output=True, timeout=30, check=True,
    )


def extract_frames_sync(video_path: str, n: int = 6) -> list[bytes]:
    """Extract n evenly spaced frames from video, return as JPEG bytes list."""
    duration = _run_ffprobe(video_path)
    frames = []
    for i in range(n):
        t = duration * (i + 0.5) / n
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            _extract_frame_at(video_path, t, tmp_path)
            with open(tmp_path, "rb") as f:
                data = f.read()
            if data:
                frames.append(data)
        except Exception as e:
            logger.warning(f"Frame extraction at t={t:.2f}s failed: {e}")
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    return frames


def extract_last_frame_sync(video_path: str) -> bytes:
    """Extract the very last frame of the video."""
    duration = _run_ffprobe(video_path)
    t = max(0.0, duration * 0.95)  # handles sub-0.5s clips
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        _extract_frame_at(video_path, t, tmp_path)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


_STORYBOARD_TOOL = {
    "name": "generate_storyboard",
    "description": "Output the cinematic continuation storyboard as structured data.",
    "input_schema": {
        "type": "object",
        "properties": {
            "character_anchors": {
                "type": "array",
                "description": "One entry per recurring character with a precise visual description.",
                "items": {
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string", "description": "Short anchor tag e.g. CHAR_A"},
                        "description": {"type": "string", "description": "One-sentence visual description"},
                    },
                    "required": ["tag", "description"],
                },
            },
            "visual_style": {"type": "string", "description": "Film's visual style, color grade, aspect feel"},
            "story_so_far": {"type": "string", "description": "1–2 sentences summarizing the original video"},
            "scenes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "story_beat": {"type": "string", "description": "One-sentence narrative description"},
                        "prompt": {"type": "string", "description": "Full cinematic motion prompt with embedded character descriptions and camera direction"},
                    },
                    "required": ["name", "story_beat", "prompt"],
                },
            },
        },
        "required": ["character_anchors", "visual_style", "story_so_far", "scenes"],
    },
}


async def _call_claude(frames: list[bytes], n_scenes: int, project_name: str) -> dict:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to backend/.env")

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    content: list[dict] = [
        {
            "type": "text",
            "text": (
                f'Project: "{project_name}"\n'
                f"Generate exactly {n_scenes} continuation scenes.\n\n"
                + MASTER_PROMPT
            ),
        }
    ]

    for i, frame_bytes in enumerate(frames):
        b64 = base64.standard_b64encode(frame_bytes).decode()
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
        })
        content.append({"type": "text", "text": f"[Frame {i + 1} of {len(frames)}]"})

    response = await client.messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        system="You are an expert cinematographer and screenwriter.",
        tools=[_STORYBOARD_TOOL],
        tool_choice={"type": "tool", "name": "generate_storyboard"},
        messages=[{"role": "user", "content": content}],
    )

    logger.info(
        f"Claude usage: input_tokens={response.usage.input_tokens} "
        f"output_tokens={response.usage.output_tokens}"
    )

    for block in response.content:
        if block.type == "tool_use":
            return block.input

    raise RuntimeError("Claude did not return a structured storyboard — check model response")


async def analyze_and_extend(
    video_path: str,
    n_scenes: int,
    project_name: str,
) -> dict:
    """
    Analyze video frames with Claude Opus and return structured storyboard data.
    Returns dict with keys: character_anchors, visual_style, story_so_far, scenes.
    """
    frames = await asyncio.to_thread(extract_frames_sync, video_path, 6)
    if not frames:
        raise RuntimeError("Could not extract any frames from the uploaded video.")

    data = await _call_claude(frames, n_scenes, project_name)

    scenes = data.get("scenes", [])[:n_scenes]
    if not scenes:
        raise RuntimeError("Claude returned no scenes. Check the video and try again.")

    data["scenes"] = scenes
    return data


async def extract_last_frame(video_path: str) -> bytes:
    """Async wrapper around last-frame extraction."""
    return await asyncio.to_thread(extract_last_frame_sync, video_path)
