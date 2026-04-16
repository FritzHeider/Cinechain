import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings
from database import init_db
from routers import projects, render, upload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database...")
    await init_db()
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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(render.router)
app.include_router(upload.router)

# Serve output videos as static files
app.mount("/outputs", StaticFiles(directory=str(settings.output_dir)), name="outputs")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
