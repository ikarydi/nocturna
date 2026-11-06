"""The adapter service. Run next to ACE-Step:

    uvicorn nocturna.adapter.app:app --host 127.0.0.1 --port 8002

and point Nocturna at it with ACE_STEP_URL=http://127.0.0.1:8002.
"""

import subprocess
import uuid
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .acestep import AceStepClient, AceStepError, build_task
from .config import AdapterSettings, get_adapter_settings


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    duration_s: int = Field(ge=10, le=600)
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)


def detect_revision(settings: AdapterSettings) -> str | None:
    if settings.acestep_revision:
        return settings.acestep_revision
    if settings.acestep_repo_dir and (settings.acestep_repo_dir / ".git").exists():
        try:
            out = subprocess.run(["git", "-C", str(settings.acestep_repo_dir), "rev-parse", "HEAD"],
                                 capture_output=True, text=True, timeout=5)
            return out.stdout.strip() or None
        except (OSError, subprocess.TimeoutExpired):
            return None
    return None


def create_adapter(settings: AdapterSettings | None = None, client: AceStepClient | None = None) -> FastAPI:
    settings = settings or get_adapter_settings()
    client = client or AceStepClient(settings.acestep_url, settings.acestep_api_key)
    media_dir = settings.media_dir.resolve()
    revision = detect_revision(settings)
    app = FastAPI(title="Nocturna generation adapter")

    @app.get("/health")
    def health():
        try:
            info = client.health()
        except AceStepError as exc:
            raise HTTPException(503, {"status": "unreachable", "error": str(exc)}) from exc
        return {
            "status": "ok",
            "model": settings.model or info.get("default_model"),
            "model_revision": revision,
            "license": settings.license,
            "acestep": info.get("acestep"),
            "media_dir": str(media_dir),
        }

    @app.post("/generate")
    def generate(body: GenerateRequest):
        task = build_task(
            prompt=body.prompt, duration_s=body.duration_s, seed=body.seed,
            model=settings.model, inference_steps=settings.inference_steps,
            audio_format=settings.audio_format, thinking=settings.thinking,
        )
        started = datetime.now(UTC)
        try:
            task_id = client.submit(task)
            result = client.wait(task_id, settings.timeout_s, settings.poll_interval_s)
            name = f"{started:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.{settings.audio_format}"
            dest = media_dir / "generated" / name
            client.download(result["file"], dest)
        except AceStepError as exc:
            raise HTTPException(502, str(exc)) from exc
        seed_value = str(result.get("seed_value") or "").split(",")[0].strip()
        return {
            "audio_path": str(dest.relative_to(media_dir)),
            "seed": int(seed_value) if seed_value.isdigit() else body.seed,
            "model": result.get("dit_model") or settings.model or None,
            "lm_model": result.get("lm_model") or None,
            "model_revision": revision,
            "license": settings.license,
            "license_url": settings.license_url,
            "engine": "ACE-Step 1.5",
            "task_id": task_id,
            "settings": {k: v for k, v in task.items() if k != "prompt"},
            "metas": result.get("metas"),
            "generation_info": result.get("generation_info"),
            "seconds_taken": round((datetime.now(UTC) - started).total_seconds(), 1),
        }

    return app


def __getattr__(name: str):
    if name == "app":
        global app
        app = create_adapter()
        return app
    raise AttributeError(name)
