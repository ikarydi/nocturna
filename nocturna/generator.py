"""Client for the normalized generation service that wraps ACE-Step.

Nocturna never talks to ACE-Step's upstream API directly. A small adapter service you
deploy next to the GPU exposes this contract:

    GET  /health   -> 200 {"status": "ok", "model": "...", "model_revision": "..."}
    POST /generate {"prompt": str, "duration_s": int, "seed": int | null}
                   -> 200 {"audio_path": str} or {"audio_url": str}, plus optional
                      "seed", "model", "model_revision", "license"

Keeping this seam narrow means upstream changes only touch the adapter.
"""

from dataclasses import dataclass
from typing import Any, Protocol

import httpx


class GeneratorError(RuntimeError):
    pass


class GenerationDisabled(GeneratorError):
    pass


@dataclass
class GenerationResult:
    audio_path: str | None
    audio_url: str | None
    metadata: dict[str, Any]


class Generator(Protocol):
    def health(self) -> dict[str, Any]: ...
    def generate(self, prompt: str, duration_s: int, seed: int | None = None) -> GenerationResult: ...


def parse_generation_response(payload: Any) -> GenerationResult:
    if not isinstance(payload, dict):
        raise GeneratorError("generator returned a non-object response")
    audio_path = payload.get("audio_path")
    audio_url = payload.get("audio_url")
    for name, value in (("audio_path", audio_path), ("audio_url", audio_url)):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise GeneratorError(f"generator returned an invalid {name}")
    if not audio_path and not audio_url:
        raise GeneratorError("generator response has neither audio_path nor audio_url")
    if audio_url and not audio_url.startswith(("http://", "https://")):
        raise GeneratorError("audio_url must be http(s)")
    metadata = {k: v for k, v in payload.items() if k not in {"audio_path", "audio_url"}}
    return GenerationResult(audio_path=audio_path, audio_url=audio_url, metadata=metadata)


class DisabledGenerator:
    """Default generator. Generation is off until ACE_STEP_ENABLED=true."""

    def health(self) -> dict[str, Any]:
        return {"status": "disabled"}

    def generate(self, prompt: str, duration_s: int, seed: int | None = None) -> GenerationResult:
        raise GenerationDisabled("generation is disabled (ACE_STEP_ENABLED=false)")


class HttpGenerator:
    def __init__(self, base_url: str, timeout_s: float = 600.0, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout_s)

    def health(self) -> dict[str, Any]:
        try:
            response = self._client.get(f"{self.base_url}/health", timeout=5.0)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return {"status": "unreachable", "error": str(exc)}
        if not isinstance(data, dict):
            return {"status": "invalid", "error": "health response is not a JSON object"}
        if "status" not in data and {"data", "code"} <= data.keys():
            # ACE-Step wraps every response as {"data", "code", ...}: the URL skips the adapter.
            return {
                "status": "wrong port",
                "error": f"ACE_STEP_URL ({self.base_url}) points at ACE-Step itself; "
                         "set it to the Nocturna adapter, usually http://127.0.0.1:8002",
            }
        if "status" not in data:
            return {"status": "invalid", "error": "health response has no status"}
        return data

    def generate(self, prompt: str, duration_s: int, seed: int | None = None) -> GenerationResult:
        try:
            response = self._client.post(
                f"{self.base_url}/generate",
                json={"prompt": prompt, "duration_s": duration_s, "seed": seed},
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise GeneratorError(f"generator returned HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise GeneratorError(f"generator request failed: {exc}") from exc
        except ValueError as exc:
            raise GeneratorError("generator returned invalid JSON") from exc
        return parse_generation_response(payload)


def build_generator(enabled: bool, url: str, timeout_s: float) -> Generator:
    return HttpGenerator(url, timeout_s) if enabled else DisabledGenerator()
