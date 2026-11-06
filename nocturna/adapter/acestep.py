"""Client for ACE-Step 1.5's REST API (docs/en/API.md in the ACE-Step repo)."""

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

INSTRUMENTAL_LYRICS = "[Instrumental]"


class AceStepError(RuntimeError):
    pass


def _unwrap(response: httpx.Response) -> Any:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            body = response.json()
            detail = body.get("detail") or body.get("error") or ""
        except ValueError:
            pass
        raise AceStepError(f"ACE-Step returned HTTP {response.status_code} {detail}".strip()) from exc
    try:
        body = response.json()
    except ValueError as exc:
        raise AceStepError("ACE-Step returned invalid JSON") from exc
    if isinstance(body, dict) and "data" in body:
        if body.get("code", 200) != 200 or body.get("error"):
            raise AceStepError(f"ACE-Step error: {body.get('error') or body.get('code')}")
        return body["data"]
    return body


def build_task(
    *, prompt: str, duration_s: int, seed: int | None, model: str, inference_steps: int,
    audio_format: str, thinking: bool,
) -> dict[str, Any]:
    task: dict[str, Any] = {
        "prompt": prompt,
        "lyrics": INSTRUMENTAL_LYRICS,
        "audio_duration": duration_s,
        "batch_size": 1,
        "audio_format": audio_format,
        "inference_steps": inference_steps,
        "thinking": thinking,
        # Keep Nocturna's constrained prompt exactly as reviewed: no LM rewriting.
        "use_cot_caption": False,
        "use_cot_language": False,
        "use_format": False,
        "task_type": "text2music",
    }
    if seed is not None:
        task["use_random_seed"] = False
        task["seed"] = seed
    if model:
        task["model"] = model
    return task


def parse_result(item: dict[str, Any]) -> dict[str, Any]:
    """Parse one entry of query_result's data list into the first generated track."""
    raw = item.get("result")
    results = json.loads(raw) if isinstance(raw, str) and raw else raw
    if not results:
        raise AceStepError("ACE-Step finished without returning audio")
    first = results[0] if isinstance(results, list) else results
    if not isinstance(first, dict) or not first.get("file"):
        raise AceStepError("ACE-Step result has no audio file")
    return first


def _failure_detail(item: dict[str, Any]) -> str:
    try:
        raw = item.get("result")
        results = json.loads(raw) if isinstance(raw, str) and raw else raw
        if isinstance(results, list) and results and isinstance(results[0], dict):
            return str(results[0].get("error") or "")
    except ValueError:
        pass
    return str(item.get("error") or "")


class AceStepClient:
    def __init__(self, base_url: str, api_key: str = "", client: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.base_url = base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.Client(timeout=60.0)
        self._headers = headers
        self._sleep = sleep
        self._clock = clock

    def _get(self, path: str, **kw) -> httpx.Response:
        try:
            return self._client.get(f"{self.base_url}{path}", headers=self._headers, **kw)
        except httpx.HTTPError as exc:
            raise AceStepError(f"cannot reach ACE-Step at {self.base_url}: {exc}") from exc

    def _post(self, path: str, payload: dict) -> httpx.Response:
        try:
            return self._client.post(f"{self.base_url}{path}", json=payload, headers=self._headers)
        except httpx.HTTPError as exc:
            raise AceStepError(f"cannot reach ACE-Step at {self.base_url}: {exc}") from exc

    def health(self) -> dict[str, Any]:
        data = _unwrap(self._get("/health", timeout=5.0))
        try:
            models = _unwrap(self._get("/v1/models", timeout=5.0))
        except AceStepError:
            models = {}
        return {"acestep": data, "default_model": (models or {}).get("default_model")}

    def submit(self, task: dict[str, Any]) -> str:
        data = _unwrap(self._post("/release_task", task))
        task_id = (data or {}).get("task_id")
        if not task_id:
            raise AceStepError("ACE-Step did not return a task_id")
        return task_id

    def wait(self, task_id: str, timeout_s: float, poll_interval_s: float) -> dict[str, Any]:
        deadline = self._clock() + timeout_s
        while True:
            data = _unwrap(self._post("/query_result", {"task_id_list": [task_id]}))
            item = next((d for d in (data or []) if d.get("task_id") == task_id), None)
            status = item.get("status") if item else 0
            if status == 1:
                return parse_result(item)
            if status == 2:
                raise AceStepError(f"ACE-Step generation failed {_failure_detail(item)}".strip())
            if self._clock() >= deadline:
                raise AceStepError(f"ACE-Step task {task_id} timed out after {timeout_s:.0f}s")
            self._sleep(poll_interval_s)

    def download(self, file_url: str, dest: Path) -> None:
        url = file_url if file_url.startswith("http") else f"{self.base_url}{file_url}"
        if not url.startswith(self.base_url):
            raise AceStepError("ACE-Step returned an audio URL on another host")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            with self._client.stream("GET", url, headers=self._headers, timeout=300.0) as r:
                if r.status_code != 200:
                    raise AceStepError(f"audio download failed: HTTP {r.status_code}")
                with tmp.open("wb") as fh:
                    for chunk in r.iter_bytes():
                        fh.write(chunk)
            if tmp.stat().st_size == 0:
                raise AceStepError("downloaded audio is empty")
            tmp.replace(dest)
        except httpx.HTTPError as exc:
            raise AceStepError(f"audio download failed: {exc}") from exc
        finally:
            tmp.unlink(missing_ok=True)
