from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class AdapterSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ADAPTER_", env_file=".env", extra="ignore")

    # Where ACE-Step's own API server listens (`uv run acestep-api`).
    acestep_url: str = "http://127.0.0.1:8001"
    acestep_api_key: str = ""

    # Must be Nocturna's AUDIO_DIR: files land in <media_dir>/generated/ and the adapter
    # returns paths relative to it.
    media_dir: Path = Path("./data/audio")

    # Generation settings sent to ACE-Step. Empty model = ACE-Step's default DiT.
    model: str = ""
    inference_steps: int = 8
    audio_format: str = "flac"
    # Use the 5Hz LM to plan audio codes. Better quality, but slow on CPU and needs more memory.
    thinking: bool = False

    # Provenance. Set ACESTEP_REVISION to the ACE-Step git commit you run (setup script does).
    acestep_revision: str = ""
    acestep_repo_dir: Path | None = None
    license: str = "MIT"
    license_url: str = "https://huggingface.co/ACE-Step/Ace-Step1.5"

    poll_interval_s: float = 2.0
    timeout_s: float = 3600.0


@lru_cache
def get_adapter_settings() -> AdapterSettings:
    return AdapterSettings()
