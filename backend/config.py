from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    fal_key: str = ""  # Required — set FAL_KEY in backend/.env
    anthropic_api_key: str = ""  # Required for /extend — set ANTHROPIC_API_KEY in backend/.env
    database_url: str = "sqlite+aiosqlite:///./cinechain.db"
    upload_dir: Path = Path("./uploads")
    output_dir: Path = Path("./outputs")
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173", "*"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.output_dir.mkdir(parents=True, exist_ok=True)
