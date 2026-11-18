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

    # Human layer: Freesound search and import (free key at https://freesound.org/apiv2/apply).
    freesound_api_key: str = ""

    # Covers: optional font files (an italic serif and a monospace); system fonts otherwise.
    cover_font_serif: str | None = None
    cover_font_mono: str | None = None

    # YouTube uploads. Off until `python -m nocturna.youtube auth` has stored a token.
    youtube_enabled: bool = False
    # Schedule uploads automatically when a release is approved (otherwise press the button).
    youtube_auto_schedule: bool = False
    youtube_client_secrets: Path = Path("./data/youtube-client-secret.json")
    youtube_token_path: Path = Path("./data/youtube-token.json")
    youtube_timezone: str = "Europe/Budapest"
    # Weekly publish slots, local time. One upload per slot keeps the cadence human.
    youtube_long_slots: str = "tue 20:00,fri 20:00"
    youtube_short_slots: str = "mon 18:00,wed 18:00,thu 18:00,sat 12:00"
    # Never schedule sooner than this, so there is time to check the private upload.
    youtube_min_lead_hours: int = 12
    # Upload Shorts too (a vertical clip from each release).
    youtube_shorts: bool = True

    # Apply Alembic migrations on startup, so a fresh clone needs no manual step.
    auto_migrate: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
