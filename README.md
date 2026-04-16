# CineChain 🎬

Cinematic multi-clip video generation pipeline using ByteDance Seedance 2.0 Fast via fal.ai.

Build storyboards, generate each scene as a video clip, then stitch them into a single
cinematic film with smooth crossfade transitions — all through a visual UI.

---

## Architecture

```
User → React UI (storyboard builder)
         ↓ REST API
       FastAPI backend
         ├── fal.ai Seedance 2.0 (per-clip generation)
         └── FFmpeg (normalization + crossfade + concat)
```

---

## Prerequisites

- Python 3.11+
- FFmpeg: `brew install ffmpeg` (macOS) or `sudo apt install ffmpeg` (Linux)
- fal.ai API key: https://fal.ai/keys

---

## Setup

### 1. Clone & install backend

```bash
cd cinechain/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and set your FAL_KEY
```

### 3. Start the API

```bash
uvicorn main:app --reload --port 8000
```

API docs available at: http://localhost:8000/docs

### 4. Use the frontend

The `frontend/CineChain.jsx` is a self-contained React component. Drop it into any
React app (Vite, CRA, Next.js) and import it as your root component. It connects to
`http://localhost:8000` by default — change the `API` constant at the top of the file.

---

## Workflow

### Step 1: Create a project
Give your cinematic project a name and description.

### Step 2: Add scenes (clips)
Each clip represents one scene in your film:
- **Start frame**: The image that begins the shot (required)
- **End frame**: Optional image to control where the shot ends (great for transitions)
- **Prompt**: Describe the motion — camera movement, action, mood
- **Duration**: 4–15 seconds, or "auto"
- **Aspect ratio**: 16:9 for cinema, 9:16 for vertical, etc.
- **Audio**: Seedance generates synchronized ambient/SFX audio at no extra cost

### Step 3: Order your storyboard
Drag clips up/down to arrange the narrative sequence. The order determines the final
video's scene order.

### Step 4: Render

**Sequential (recommended)**: Clips generate one at a time in order. Lower risk of
hitting rate limits. Each completed clip's video URL could be used as the next clip's
end_image_url for continuity.

**Parallel**: All clips are submitted to fal.ai simultaneously. Faster overall, but
all jobs are in-flight at once.

### Step 5: Stitch
After all clips complete, the backend:
1. Downloads each clip video from fal CDN
2. Normalizes all clips to consistent codec/fps/resolution
3. Applies crossfade transitions between clips (configurable duration)
4. Concatenates into the final MP4
5. Makes it available for download

---

## API Reference

### Projects
```
GET    /projects              List all projects
POST   /projects              Create project { name, description }
GET    /projects/{id}         Get project + all clips
PATCH  /projects/{id}         Update project
DELETE /projects/{id}         Delete project + clips
```

### Clips
```
POST   /projects/{id}/clips              Add clip
GET    /projects/{id}/clips              List clips
PATCH  /projects/{id}/clips/{cid}        Update clip
DELETE /projects/{id}/clips/{cid}        Delete clip
POST   /projects/{id}/clips/reorder      Reorder by ID list
```

### Render
```
POST   /projects/{id}/render                   Start render (parallel or sequential)
GET    /projects/{id}/render/status            Poll render progress
POST   /projects/{id}/render/stitch            Manually trigger stitch
POST   /projects/{id}/clips/{cid}/generate     Submit single clip to fal.ai
GET    /projects/{id}/clips/{cid}/poll         Poll single clip fal job
GET    /projects/{id}/download                 Download final stitched video
```

### Upload
```
POST   /upload/image    Upload image → returns fal.ai public URL
```

---

## Cinematic tips

### Continuity between clips
For smooth narrative flow, use the **end frame** feature:
1. Screenshot or save the last frame of clip N
2. Use it as the **start frame** of clip N+1
3. This creates visual continuity across scene cuts

### Prompting for motion
Good prompts describe:
- Camera movement: "slow dolly forward", "pan left", "crane shot descending"
- Subject action: "character walks toward the light"
- Mood: "golden hour haze", "dramatic shadows deepen"
- Pacing: "slow motion", "time-lapse"

### Crossfade duration
The default 0.5s crossfade works for most transitions. For more dramatic cuts use 0s,
for dreamy dissolves use 1.0–1.5s. Adjust via the `/stitch` endpoint's
`crossfade_duration` query param.

### Resolution strategy
- **720p** (default): Best quality, higher cost ($0.2419/sec)
- **480p**: Faster generation, lower cost — good for drafts/previews

---

## Cost estimation

Seedance 2.0 Fast: **$0.2419 per second of 720p video**

| Clips | Avg duration | Estimated cost |
|-------|-------------|----------------|
| 5 clips | 8 sec each | ~$9.68 |
| 10 clips | 6 sec each | ~$14.51 |
| 20 clips | 5 sec each | ~$24.19 |

---

## Project structure

```
cinechain/
├── backend/
│   ├── main.py                   FastAPI app + CORS + lifespan
│   ├── config.py                 Settings (FAL_KEY, paths)
│   ├── database.py               SQLAlchemy async models (Project, Clip)
│   ├── models.py                 Pydantic request/response schemas
│   ├── requirements.txt
│   ├── .env.example
│   ├── routers/
│   │   ├── projects.py           Project + Clip CRUD
│   │   ├── render.py             Orchestration: submit, poll, stitch
│   │   └── upload.py             Image upload → fal storage
│   └── services/
│       ├── fal_service.py        fal.ai Seedance 2.0 client
│       ├── stitch_service.py     FFmpeg download + normalize + concat
│       └── upload_service.py     Local save + fal upload
└── frontend/
    └── CineChain.jsx             React storyboard builder UI
```
# Cinechain
