"""A stand-in for ACE-Step's API server, for trying the generation flow without a GPU
or model download. It speaks the same endpoints and returns a synthetic drone made with
ffmpeg (low sine + pink noise, pitch chosen from the seed). It is not music generation.

    uvicorn nocturna.adapter.fake_acestep:app --host 127.0.0.1 --port 8001
"""

import json
import random
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

FAKE_MODEL = "fake-acestep-drone"


def _envelope(data):
    return {"data": data, "code": 200, "error": None, "timestamp": int(time.time() * 1000),
            "extra": None}


def render(dest: Path, seconds: float, seed: int, fmt: str) -> None:
    rng = random.Random(seed)
    base = rng.choice([55.0, 61.7, 65.4, 73.4, 82.4])
    fade_out = max(seconds - 4, 0)
    graph = (
        f"[0][1][2]amix=inputs=3:normalize=0,volume=0.35,"
        f"aecho=0.8:0.7:{rng.randint(300, 900)}:0.4,"
        f"afade=t=in:d=3,afade=t=out:st={fade_out}:d=4"
    )
    codec = {"flac": ["-c:a", "flac"], "wav": ["-c:a", "pcm_s16le"], "mp3": ["-c:a", "libmp3lame"]}
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"sine=f={base}:d={seconds}:sample_rate=48000",
         "-f", "lavfi", "-i", f"sine=f={base * 1.5:.2f}:d={seconds}:sample_rate=48000",
         "-f", "lavfi", "-i", f"anoisesrc=d={seconds}:c=brown:a=0.08:r=48000:seed={seed % 2**31}",
         "-filter_complex", graph, "-t", str(seconds), "-ac", "2",
         *codec.get(fmt, codec["flac"]), str(dest)],
        check=True,
    )


def create_fake(delay_s: float = 1.0, out_dir: Path | None = None) -> FastAPI:
    out = out_dir or Path(tempfile.mkdtemp(prefix="fake-acestep-"))
    out.mkdir(parents=True, exist_ok=True)
    tasks: dict[str, dict] = {}
    app = FastAPI(title="Fake ACE-Step")

    @app.get("/health")
    def health():
        return _envelope({"status": "ok", "service": "Fake ACE-Step API", "version": "fake"})

    @app.get("/v1/models")
    def models():
        return _envelope({"models": [{"name": FAKE_MODEL, "is_default": True}],
                          "default_model": FAKE_MODEL})

    @app.post("/release_task")
    async def release_task(request: Request):
        body = await request.json()
        if body.get("lyrics") != "[Instrumental]":
            raise HTTPException(400, "fake server only accepts instrumental requests")
        task_id = str(uuid.uuid4())
        seed = body.get("seed") if body.get("use_random_seed") is False else random.randrange(2**31)
        fmt = body.get("audio_format", "flac")
        tasks[task_id] = {"status": 0, "body": body, "seed": seed}

        def work():
            time.sleep(delay_s)
            path = out / f"{task_id}.{fmt}"
            try:
                render(path, float(body.get("audio_duration") or 30), int(seed), fmt)
            except Exception as exc:  # noqa: BLE001
                tasks[task_id].update(status=2, error=str(exc))
                return
            tasks[task_id].update(status=1, path=str(path))

        threading.Thread(target=work, daemon=True).start()
        return _envelope({"task_id": task_id, "status": "queued", "queue_position": 1})

    @app.post("/query_result")
    async def query_result(request: Request):
        ids = (await request.json()).get("task_id_list", [])
        data = []
        for tid in ids:
            t = tasks.get(tid)
            if t is None:
                continue
            item = {"task_id": tid, "status": t["status"]}
            if t["status"] == 1:
                item["result"] = json.dumps([{
                    "file": f"/v1/audio?path={quote(t['path'])}", "status": 1,
                    "prompt": t["body"].get("prompt"), "lyrics": "[Instrumental]",
                    "metas": {"duration": t["body"].get("audio_duration")},
                    "seed_value": str(t["seed"]), "dit_model": FAKE_MODEL, "lm_model": None,
                    "generation_info": "synthetic drone from fake_acestep (not a real model)",
                }])
            elif t["status"] == 2:
                item["result"] = json.dumps([{"status": 2, "error": t.get("error", "")}])
            data.append(item)
        return _envelope(data)

    @app.get("/v1/audio")
    def audio(path: str):
        p = Path(path).resolve()
        if not p.is_relative_to(out.resolve()) or not p.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(p)

    return app


def __getattr__(name: str):
    if name == "app":
        global app
        app = create_fake()
        return app
    raise AttributeError(name)
