import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings
from database import init_db
from routers import projects, render, upload, extend

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _cleanup_stale_uploads(max_age_hours: int = 24) -> None:
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for f in settings.upload_dir.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    if removed:
        logger.info(f"Cleaned up {removed} stale upload files (>{max_age_hours}h old)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database...")
    await init_db()
    _cleanup_stale_uploads()
    logger.info("CineChain API ready.")
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="CineChain API",
    description="Cinematic multi-clip video generation workflow using Seedance 2.0",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(render.router)
app.include_router(upload.router)
app.include_router(extend.router)

# Serve final output videos only — uploads are temp files, not publicly exposed
app.mount("/outputs", StaticFiles(directory=str(settings.output_dir)), name="outputs")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
