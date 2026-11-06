import json

import httpx
import pytest
from fastapi.testclient import TestClient

from nocturna.adapter.acestep import AceStepClient, AceStepError, build_task, parse_result
from nocturna.adapter.app import create_adapter
from nocturna.adapter.config import AdapterSettings
from nocturna.adapter.fake_acestep import create_fake
from nocturna.api import create_app
from nocturna.config import Settings
from nocturna.generator import HttpGenerator

from .conftest import needs_ffmpeg


def env(data, code=200, error=None):
    return {"data": data, "code": code, "error": error, "timestamp": 0, "extra": None}


def mock_client(handler, **kw):
    return AceStepClient("http://ace", client=httpx.Client(transport=httpx.MockTransport(handler)),
                         sleep=lambda s: None, **kw)


def test_build_task_keeps_prompt_and_forces_instrumental():
    t = build_task(prompt="dark drone", duration_s=60, seed=42, model="acestep-v15-turbo",
                   inference_steps=8, audio_format="flac", thinking=False)
    assert t["lyrics"] == "[Instrumental]" and t["prompt"] == "dark drone"
    assert t["use_cot_caption"] is False and t["use_format"] is False
    assert t["use_random_seed"] is False and t["seed"] == 42 and t["batch_size"] == 1
    assert "seed" not in build_task(prompt="x", duration_s=30, seed=None, model="",
                                    inference_steps=8, audio_format="flac", thinking=False)


def test_parse_result_variants():
    item = {"result": json.dumps([{"file": "/v1/audio?path=a.flac", "seed_value": "1,2"}])}
    assert parse_result(item)["file"].endswith("a.flac")
    for bad in ({"result": "[]"}, {"result": json.dumps([{"status": 1}])}, {}):
        with pytest.raises(AceStepError):
            parse_result(bad)


def test_submit_poll_download(tmp_path):
    polls = {"n": 0}

    def handler(req: httpx.Request):
        if req.url.path == "/release_task":
            body = json.loads(req.content)
            assert body["lyrics"] == "[Instrumental]"
            return httpx.Response(200, json=env({"task_id": "t1", "status": "queued"}))
        if req.url.path == "/query_result":
            polls["n"] += 1
            if polls["n"] < 3:
                return httpx.Response(200, json=env([{"task_id": "t1", "status": 0}]))
            res = [{"file": "/v1/audio?path=%2Ftmp%2Fx.flac", "seed_value": "7"}]
            return httpx.Response(200, json=env([{"task_id": "t1", "status": 1, "result": json.dumps(res)}]))
        if req.url.path == "/v1/audio":
            return httpx.Response(200, content=b"fLaC-data")
        return httpx.Response(404)

    c = mock_client(handler)
    tid = c.submit({"prompt": "p", "lyrics": "[Instrumental]"})
    result = c.wait(tid, timeout_s=60, poll_interval_s=0)
    assert polls["n"] == 3 and result["seed_value"] == "7"
    c.download(result["file"], tmp_path / "out.flac")
    assert (tmp_path / "out.flac").read_bytes() == b"fLaC-data"


def test_failed_task_and_timeout():
    def failed(req):
        if req.url.path == "/query_result":
            return httpx.Response(200, json=env([{"task_id": "t", "status": 2,
                                                  "result": json.dumps([{"file": "", "error": "OOM"}])}]))
        return httpx.Response(404)

    with pytest.raises(AceStepError, match="failed OOM"):
        mock_client(failed).wait("t", 60, 0)

    def pending(req):
        return httpx.Response(200, json=env([{"task_id": "t", "status": 0}]))

    ticks = iter(range(0, 10_000, 100))
    c = AceStepClient("http://ace", client=httpx.Client(transport=httpx.MockTransport(pending)),
                      sleep=lambda s: None, clock=lambda: next(ticks))
    with pytest.raises(AceStepError, match="timed out"):
        c.wait("t", timeout_s=250, poll_interval_s=0)


def test_errors_are_wrapped(tmp_path):

    c = mock_client(lambda r: httpx.Response(429, json={"detail": "queue full"}))
    with pytest.raises(AceStepError, match="429 queue full"):
        c.submit({})
    c = mock_client(lambda r: httpx.Response(200, json=env(None, code=500, error="boom")))
    with pytest.raises(AceStepError, match="boom"):
        c.submit({})

    def refused(req):
        raise httpx.ConnectError("refused")

    with pytest.raises(AceStepError, match="cannot reach"):
        mock_client(refused).health()
    with pytest.raises(AceStepError, match="another host"):
        mock_client(lambda r: httpx.Response(200)).download("http://evil/x.flac", tmp_path / "x")
    with pytest.raises(AceStepError, match="empty"):
        mock_client(lambda r: httpx.Response(200, content=b"")).download("/v1/audio?path=x", tmp_path / "e.flac")
    assert not (tmp_path / "e.flac").exists() and not (tmp_path / "e.flac.part").exists()


def test_adapter_health_unreachable(tmp_path):
    def refused(req):
        raise httpx.ConnectError("refused")

    app = create_adapter(AdapterSettings(_env_file=None, media_dir=tmp_path), mock_client(refused))
    with TestClient(app) as c:
        r = c.get("/health")
    assert r.status_code == 503 and r.json()["detail"]["status"] == "unreachable"


def test_adapter_rejects_bad_requests(tmp_path):
    app = create_adapter(AdapterSettings(_env_file=None, media_dir=tmp_path), mock_client(lambda r: httpx.Response(404)))
    with TestClient(app) as c:
        assert c.post("/generate", json={"prompt": "", "duration_s": 30}).status_code == 422
        assert c.post("/generate", json={"prompt": "x", "duration_s": 5}).status_code == 422
        assert c.post("/generate", json={"prompt": "x", "duration_s": 30}).status_code == 502


@pytest.fixture
def fake_chain(tmp_path):
    """Fake ACE-Step <- adapter, both in-process. Returns (adapter TestClient, media_dir)."""
    media = tmp_path / "audio"
    fake = TestClient(create_fake(delay_s=0, out_dir=tmp_path / "fake-out"), base_url="http://ace")
    ace = AceStepClient("http://ace", client=fake, sleep=lambda s: None)
    settings = AdapterSettings(_env_file=None, media_dir=media, acestep_revision="ca1e85fe",
                               poll_interval_s=0.05, timeout_s=30)
    adapter = TestClient(create_adapter(settings, ace), base_url="http://adapter")
    return adapter, media


@needs_ffmpeg
def test_adapter_against_fake_acestep(fake_chain):
    adapter, media = fake_chain
    h = adapter.get("/health").json()
    assert h["status"] == "ok" and h["model"] == "fake-acestep-drone" and h["model_revision"] == "ca1e85fe"
    r = adapter.post("/generate", json={"prompt": "dark drone, no vocals", "duration_s": 12, "seed": 99})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["audio_path"].startswith("generated/") and (media / out["audio_path"]).stat().st_size > 0
    assert out["seed"] == 99 and out["model"] == "fake-acestep-drone" and out["license"] == "MIT"
    assert out["settings"]["lyrics"] == "[Instrumental]" and out["settings"]["use_cot_caption"] is False


@needs_ffmpeg
def test_nocturna_end_to_end_with_fake_generation(fake_chain, tmp_path):
    adapter, media = fake_chain
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'n.db'}",
                        audio_dir=media, ace_step_enabled=True)
    gen = HttpGenerator("http://adapter", client=adapter)
    with TestClient(create_app(settings, gen)) as c:
        assert c.get("/health").json()["generator"]["status"] == "ok"
        rel = c.post("/api/releases", json={"title": "Vesper", "brief": "organ drone", "duration_s": 15, "seed": 5}).json()
        run = c.post(f"/api/releases/{rel['id']}/run").json()
        assert run["status"] == "review", run
        (take,) = run["assets"]
        p = take["provenance"]
        assert p["source"] == "generated" and p["seed"] == 5 and p["model"] == "fake-acestep-drone"
        assert p["model_revision"] == "ca1e85fe" and p["license"] == "MIT" and p["prompt"] == run["prompt"]
        assert take["sample_rate"] == 48000 and abs(take["duration_s"] - 15) < 0.5
        assert "provenance incomplete" not in (run["workflow_note"] or "")
        r = c.post(f"/api/releases/{rel['id']}/export")
        assert r.status_code == 200 and {a["kind"] for a in r.json()["assets"]} == {"take", "master", "delivery"}
