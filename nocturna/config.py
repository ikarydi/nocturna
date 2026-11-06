from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, read from environment variables or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./data/nocturna.db"
    audio_dir: Path = Path("./data/audio")

    # Generation stays off until a GPU-backed service is deployed and health-checked.
    ace_step_enabled: bool = False
    # URL of the Nocturna generation adapter (nocturna.adapter), not ACE-Step itself.
    ace_step_url: str = "http://127.0.0.1:8002"
    # CPU generation can take many minutes per clip.
    ace_step_timeout_s: float = 3600.0

    # Delivery export targets (YouTube normalizes playback to about -14 LUFS).
    delivery_lufs: float = -14.0
    delivery_true_peak_dbtp: float = -1.0
    max_upload_mb: int = 1024

    # Apply Alembic migrations on startup, so a fresh clone needs no manual step.
    auto_migrate: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
