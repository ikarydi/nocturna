from nocturna.generator import GenerationResult

from .conftest import FakeGenerator


def create(client, **extra):
    body = {"title": "Ashes Over Vesper", "lane": "dark ambient", "brief": "slow organ drones", **extra}
    r = client.post("/api/releases", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_health_reports_generation_off(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["database"] == "sqlite"
    assert h["generation_enabled"] is False and h["generator"]["status"] == "disabled"


def test_dashboard_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Nocturna" in r.text
    assert client.get("/static/app.js").status_code == 200


def test_create_review_approve_flow(client):
    rel = create(client)
    assert rel["status"] == "draft" and rel["prompt"] is None

    run = client.post(f"/api/releases/{rel['id']}/run").json()
    assert run["status"] == "review"
    assert "no vocals" in run["prompt"]

    done = client.post(f"/api/releases/{rel['id']}/decision", json={"action": "approve", "note": "ok"}).json()
    assert done["status"] == "approved"
    assert [e["action"] for e in done["events"]] == ["create", "submit_for_review", "approve"]


def test_reject_requires_note_then_reopen(client):
    rel = create(client)
    client.post(f"/api/releases/{rel['id']}/run")
    r = client.post(f"/api/releases/{rel['id']}/decision", json={"action": "reject"})
    assert r.status_code == 409 and "note" in r.json()["detail"]
    # The failed attempt must not have changed anything.
    assert client.get(f"/api/releases/{rel['id']}").json()["status"] == "review"

    r = client.post(f"/api/releases/{rel['id']}/decision", json={"action": "reject", "note": "too close to last week"})
    assert r.json()["status"] == "rejected"
    r = client.patch(f"/api/releases/{rel['id']}", json={"brief": "new idea"})
    assert r.status_code == 200 and r.json()["brief"] == "new idea"
    r = client.post(f"/api/releases/{rel['id']}/decision", json={"action": "reopen"})
    assert r.json()["status"] == "draft"


def test_invalid_transitions_rejected(client):
    rel = create(client)
    assert client.post(f"/api/releases/{rel['id']}/decision", json={"action": "approve"}).status_code == 409
    client.post(f"/api/releases/{rel['id']}/run")
    assert client.post(f"/api/releases/{rel['id']}/run").status_code == 409
    assert client.patch(f"/api/releases/{rel['id']}", json={"title": "x"}).status_code == 409
    assert client.post(f"/api/releases/{rel['id']}/decision", json={"action": "publish"}).status_code == 422


def test_validation_and_not_found(client):
    assert client.post("/api/releases", json={"title": ""}).status_code == 422
    assert client.post("/api/releases", json={"title": "x", "bpm": 500}).status_code == 422
    assert client.get("/api/releases/999").status_code == 404


def test_list_filter(client):
    a, b = create(client, title="A"), create(client, title="B")
    client.post(f"/api/releases/{a['id']}/run")
    review = client.get("/api/releases", params={"status": "review"}).json()
    assert [r["title"] for r in review] == ["A"]
    assert len(client.get("/api/releases").json()) == 2


def test_status_persists_across_restart(settings, make_client):
    c1 = make_client(settings)
    rel = create(c1)
    c1.post(f"/api/releases/{rel['id']}/run")
    c1.post(f"/api/releases/{rel['id']}/decision", json={"action": "approve"})
    c1.__exit__(None, None, None)

    c2 = make_client(settings)
    again = c2.get(f"/api/releases/{rel['id']}").json()
    assert again["status"] == "approved" and len(again["events"]) == 3


def test_enabled_generation_attaches_and_serves_audio(settings, make_client):
    settings.ace_step_enabled = True
    settings.audio_dir.mkdir(parents=True, exist_ok=True)
    (settings.audio_dir / "take1.wav").write_bytes(b"RIFF....WAVE")
    c = make_client(settings, FakeGenerator())
    rel = create(c)
    run = c.post(f"/api/releases/{rel['id']}/run").json()
    assert run["status"] == "review" and run["has_audio"] is True
    assert [e["action"] for e in run["events"]] == ["create", "start_generation", "submit_for_review"]
    assert c.get(f"/api/releases/{rel['id']}/audio").content == b"RIFF....WAVE"


def test_audio_outside_audio_dir_is_not_served(settings, make_client, tmp_path):
    settings.ace_step_enabled = True
    (tmp_path / "secret.wav").write_bytes(b"x")
    gen = FakeGenerator(GenerationResult(str(tmp_path / "secret.wav"), None, {}))
    c = make_client(settings, gen)
    rel = create(c)
    run = c.post(f"/api/releases/{rel['id']}/run").json()
    assert run["has_audio"] is False
    assert c.get(f"/api/releases/{rel['id']}/audio").status_code == 404


def test_generation_failure_marks_failed(settings, make_client):
    settings.ace_step_enabled = True
    c = make_client(settings, FakeGenerator(error="cuda oom"))
    rel = create(c)
    run = c.post(f"/api/releases/{rel['id']}/run").json()
    assert run["status"] == "failed" and "cuda oom" in run["workflow_note"]
    assert c.post(f"/api/releases/{rel['id']}/decision", json={"action": "reopen"}).json()["status"] == "draft"
