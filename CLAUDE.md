# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CineChain is a cinematic multi-clip video generation pipeline. Users build storyboards in a React UI, the FastAPI backend submits each clip to fal.ai's Seedance 2.0 Fast (image-to-video), then FFmpeg normalizes and stitches the clips into a final MP4 with crossfade transitions.

## Commands

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then set FAL_KEY=...
uvicorn main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

### Frontend

```bash
cd frontend
npm install
npm run dev        # Vite dev server on http://localhost:5173
npm run build
npm run lint
```

The frontend's `API` constant at the top of `src/App.jsx` must point to the running backend (default: `http://localhost:8000`).

### Dependencies

FFmpeg must be installed separately:
- macOS: `brew install ffmpeg`
- Linux: `sudo apt install ffmpeg`

## Architecture

```
React UI (src/App.jsx)
    ↓ REST via fetch()
FastAPI (backend/main.py)
    ├── routers/projects.py    — Project + Clip CRUD
    ├── routers/render.py      — Render orchestration (submit, poll, stitch)
    └── routers/upload.py      — Image upload → fal storage URL
         ↓
    services/fal_service.py    — fal.ai Seedance 2.0 client (submit_async / poll / sync)
    services/stitch_service.py — FFmpeg: download → normalize → xfade → concat
    services/upload_service.py — Local save + fal.upload_file
         ↓
    database.py                — SQLAlchemy async (SQLite via aiosqlite)
    config.py                  — Pydantic settings (FAL_KEY, paths, CORS)
```

### Data model

- **Project**: `id, name, description, status (draft|rendering|complete|error), final_video_url`
- **Clip**: belongs to Project, holds `prompt, image_url, end_image_url, resolution, duration, aspect_ratio, generate_audio, seed`, plus generation state `status (pending|queued|generating|complete|error), fal_request_id, video_url`

### Render flow

**Sequential** (`POST /projects/{id}/render` with `parallel=false`): clips are generated one at a time using `fal_service.run_clip_sync()` which blocks until each finishes, then stitches automatically.

**Parallel** (`parallel=true`): all clips are submitted via `fal_service.submit_clip()` (returns `request_id` immediately). The frontend polls `/projects/{id}/clips/{cid}/poll` which calls `fal_service.poll_clip()`.

**Stitch** (`POST /projects/{id}/render/stitch`): calls `stitch_service.stitch_clips()` which downloads all complete clip URLs, normalizes to H.264/AAC/24fps, chains xfade transitions via FFmpeg `xfade` filter, and writes the final MP4 to `backend/outputs/`. The file is served as a static mount at `/outputs/`.

### Frontend structure

`src/App.jsx` is the entire frontend — a single file with three components:
- `App` — top-level router (projects list vs project detail)
- `ProjectList` — lists/creates/deletes projects
- `ProjectView` — shows clips, render controls, activity log; polls backend every 6s during rendering
- `ClipCard` — per-clip editor (prompt, images, settings), inline save/generate/poll

All styles are inline JS objects (no CSS files, no styling library).

## Key configuration

`backend/.env`:
```
FAL_KEY=your_fal_key_here
```

Optional overrides (all have defaults):
```
DATABASE_URL=sqlite+aiosqlite:///./cinechain.db
UPLOAD_DIR=./uploads
OUTPUT_DIR=./outputs
```

CORS allows all origins by default (`"*"`). Tighten in production via `cors_origins` in `.env`.

## fal.ai model

The model ID is hardcoded in `fal_service.py`:
```python
FAL_MODEL = "bytedance/seedance-2.0/fast/image-to-video"
```

Pricing: ~$0.2419/sec of 720p video generated.
