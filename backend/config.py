from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    fal_key: str = ""  # Required — set FAL_KEY in backend/.env
    groq_api_key: str = ""  # Required for /extend when extend_backend=groq
    openrouter_api_key: str = ""  # Required for /extend when extend_backend=openrouter
    extend_backend: str = "groq"  # "groq" or "openrouter"
    openrouter_model: str = "google/gemma-3-27b-it:free"  # any vision-capable model on openrouter.ai
    database_url: str = "sqlite+aiosqlite:///./cinechain.db"
    upload_dir: Path = Path("./uploads")
    output_dir: Path = Path("./outputs")
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173", "*"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.output_dir.mkdir(parents=True, exist_ok=True)
