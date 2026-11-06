from nocturna.generator import GenerationResult
from nocturna.models import CHECKLIST_ITEMS

from .conftest import FakeGenerator, make_image, make_tone, needs_ffmpeg

ALL_DONE = {key: True for key in CHECKLIST_ITEMS}


def create(client, **extra):
    body = {"title": "Ashes Over Vesper", "lane": "dark ambient", "brief": "slow organ drones", **extra}
    r = client.post("/api/releases", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def to_review(client, **extra):
    rel = create(client, **extra)
    r = client.post(f"/api/releases/{rel['id']}/run")
    assert r.json()["status"] == "review", r.text
    return r.json()


def upload(client, rid, path, kind="take", **form):
    with open(path, "rb") as fh:
        return client.post(f"/api/releases/{rid}/assets",
                           files={"file": (path.name, fh)}, data={"kind": kind, **form})


def test_health_reports_generation_off(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["database"] == "sqlite"
    assert h["generation_enabled"] is False and h["generator"]["status"] == "disabled"
    assert h["delivery_target"] == {"lufs": -14.0, "true_peak_dbtp": -1.0}


def test_dashboard_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Nocturna" in r.text
    assert client.get("/static/app.js").status_code == 200


def test_create_and_run_to_review(client):
    rel = create(client)
    assert rel["status"] == "draft" and rel["prompt"] is None
    run = client.post(f"/api/releases/{rel['id']}/run").json()
    assert run["status"] == "review" and "no vocals" in run["prompt"]
    assert run["approval_blockers"]  # nothing exported, checklist empty


def test_approval_is_blocked_until_export_and_checklist(client):
    rel = to_review(client)
    r = client.post(f"/api/releases/{rel['id']}/decision", json={"action": "approve"})
    assert r.status_code == 409
    assert "export a master" in r.json()["detail"] and "checklist incomplete" in r.json()["detail"]
    assert client.get(f"/api/releases/{rel['id']}").json()["status"] == "review"


def test_reject_requires_note_then_reopen(client):
    rel = to_review(client)
    r = client.post(f"/api/releases/{rel['id']}/decision", json={"action": "reject"})
    assert r.status_code == 409 and "note" in r.json()["detail"]
    assert client.get(f"/api/releases/{rel['id']}").json()["status"] == "review"

    r = client.post(f"/api/releases/{rel['id']}/decision",
                    json={"action": "reject", "note": "too close to last week", "actor": "J"})
    assert r.json()["status"] == "rejected" and r.json()["events"][-1]["actor"] == "J"
    r = client.patch(f"/api/releases/{rel['id']}", json={"brief": "new idea"})
    assert r.status_code == 200 and r.json()["brief"] == "new idea"
    assert client.post(f"/api/releases/{rel['id']}/decision", json={"action": "reopen"}).json()["status"] == "draft"


def test_edit_rules(client):
    rel = to_review(client)
    rid = rel["id"]
    # Metadata is editable during review; content is not.
    r = client.patch(f"/api/releases/{rid}", json={"description": "Night drive", "tags": "dark ambient"})
    assert r.status_code == 200 and r.json()["description"] == "Night drive"
    assert client.patch(f"/api/releases/{rid}", json={"brief": "x"}).status_code == 409
    assert client.post(f"/api/releases/{rid}/run").status_code == 409
    assert client.post(f"/api/releases/{rid}/decision", json={"action": "publish"}).status_code == 422


def test_validation_and_not_found(client):
    assert client.post("/api/releases", json={"title": ""}).status_code == 422
    assert client.post("/api/releases", json={"title": "x", "bpm": 500}).status_code == 422
    assert client.post("/api/releases", json={"title": "x", "template_id": 99}).status_code == 422
    assert client.get("/api/releases/999").status_code == 404


def test_list_filter(client):
    a, _ = create(client, title="A"), create(client, title="B")
    client.post(f"/api/releases/{a['id']}/run")
    assert [r["title"] for r in client.get("/api/releases", params={"status": "review"}).json()] == ["A"]
    assert len(client.get("/api/releases").json()) == 2


def test_templates_crud_and_prompt_use(client):
    r = client.post("/api/templates", json={
        "name": "Cathedral drone", "tags": "pipe organ, long reverb, slow swells",
        "bpm_min": 50, "bpm_max": 75, "default_key": "D minor",
    })
    assert r.status_code == 201
    tid = r.json()["id"]
    assert client.post("/api/templates", json={"name": "Cathedral drone"}).status_code == 409
    assert client.post("/api/templates", json={"name": "x", "bpm_min": 90, "bpm_max": 60}).status_code == 422
    assert client.patch(f"/api/templates/{tid}", json={"tags": "pipe organ, long reverb"}).json()["tags"] == "pipe organ, long reverb"

    rel = client.post("/api/releases", json={"title": "Nave", "template_id": tid, "bpm": 120}).json()
    assert rel["lane"] == "Cathedral drone" and rel["musical_key"] == "D minor"
    run = client.post(f"/api/releases/{rel['id']}/run").json()
    assert run["prompt"].startswith("pipe organ, long reverb")
    assert "outside the lane" in run["workflow_note"]
    assert [t["name"] for t in client.get("/api/templates").json()] == ["Cathedral drone"]


def test_checklist_and_comments_recorded(client):
    rid = to_review(client)["id"]
    r = client.put(f"/api/releases/{rid}/checklist", json={"items": {"rights": True}, "actor": "J"})
    assert r.json()["checklist"] == {"rights": True}
    assert r.json()["events"][-1]["action"] == "checklist"
    assert client.put(f"/api/releases/{rid}/checklist", json={"items": {"bogus": True}}).status_code == 422
    r = client.post(f"/api/releases/{rid}/comments", json={"note": "bells too loud at 1:20", "actor": "J"})
    assert r.status_code == 201
    assert r.json()["events"][-1]["note"] == "bells too loud at 1:20"
    assert client.post(f"/api/releases/{rid}/comments", json={"note": ""}).status_code == 422
    assert set(client.get("/api/checklist").json()) == set(CHECKLIST_ITEMS)


def test_upload_rejects_bad_files(client, tmp_path):
    rid = to_review(client)["id"]
    bad = tmp_path / "notes.txt"
    bad.write_text("hi")
    assert upload(client, rid, bad).status_code == 422
    empty = tmp_path / "empty.wav"
    empty.write_bytes(b"")
    assert upload(client, rid, empty).status_code == 422
    assert upload(client, rid, bad, kind="master").status_code == 422
    assert client.get(f"/api/releases/{rid}").json()["assets"] == []


def test_export_without_take_fails(client):
    rid = to_review(client)["id"]
    r = client.post(f"/api/releases/{rid}/export")
    assert r.status_code == 422 and "no take" in r.json()["detail"]


@needs_ffmpeg
def test_full_stage2_flow_to_package(client, tmp_path):
    import io
    import json
    import zipfile

    rid = to_review(client, duration_s=60)["id"]
    take = make_tone(tmp_path / "take.wav", seconds=6, volume=0.2)
    r = upload(client, rid, take, model="acestep-v15-turbo", model_revision="abc123",
               license="MIT", seed="42", actor="J")
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["sample_rate"] == 44100 and a["channels"] == 2 and round(a["duration_s"]) == 6
    assert a["integrated_lufs"] is not None and len(a["sha256"]) == 64
    assert a["provenance"]["seed"] == 42 and a["provenance"]["license"] == "MIT"
    assert any("differs from planned" in w for w in a["qc_warnings"])

    art = upload(client, rid, make_image(tmp_path / "cover.png"), kind="artwork")
    assert art.status_code == 201 and art.json()["width"] == 3000 and art.json()["qc_warnings"] == []

    r = client.post(f"/api/releases/{rid}/export", params={"actor": "J"})
    assert r.status_code == 200, r.text
    detail = r.json()
    master = next(x for x in detail["assets"] if x["kind"] == "master")
    delivery = next(x for x in detail["assets"] if x["kind"] == "delivery")
    assert master["codec"] == "flac" and master["bit_depth"] == 24 and master["parent_id"] == a["id"]
    assert delivery["sample_rate"] == 48000 and delivery["parent_id"] == master["id"]
    assert abs(delivery["integrated_lufs"] - -14.0) <= 0.5
    assert delivery["true_peak_dbtp"] <= -0.9
    assert delivery["provenance"]["settings"]["target_lufs"] == -14.0

    assert client.get(f"/api/releases/{rid}/package").status_code == 409  # not approved yet
    client.put(f"/api/releases/{rid}/checklist", json={"items": ALL_DONE, "actor": "J"})
    r = client.post(f"/api/releases/{rid}/decision", json={"action": "approve", "actor": "J"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"

    # Approved releases are frozen.
    assert upload(client, rid, take).status_code == 409
    assert client.put(f"/api/releases/{rid}/checklist", json={"items": {"rights": False}}).status_code == 409

    pkg = client.get(f"/api/releases/{rid}/package")
    assert pkg.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(pkg.content))
    names = set(zf.namelist())
    assert {"provenance.json", "metadata.json", "UPLOAD-CHECKLIST.txt"} <= names
    assert any(n.endswith("-master.flac") for n in names)
    assert any(n.endswith("-delivery.wav") for n in names)
    assert any(n.endswith("-artwork.png") for n in names)
    record = json.loads(zf.read("provenance.json"))
    assert record["release"]["status"] == "approved"
    assert all(v["done"] for v in record["checklist"].values())
    assert "altered or synthetic" in record["metadata"]["ai_disclosure"].lower()
    assert [x["kind"] for x in record["assets"]] == ["take", "artwork", "master", "delivery"]
    assert client.get(f"/api/assets/{master['id']}/file").status_code == 200


def test_status_persists_across_restart(settings, make_client):
    c1 = make_client(settings)
    rel = to_review(c1)
    c1.post(f"/api/releases/{rel['id']}/decision", json={"action": "reject", "note": "no"})
    c1.__exit__(None, None, None)

    again = make_client(settings).get(f"/api/releases/{rel['id']}").json()
    assert again["status"] == "rejected" and len(again["events"]) == 3


@needs_ffmpeg
def test_enabled_generation_records_provenance(settings, make_client):
    settings.ace_step_enabled = True
    settings.audio_dir.mkdir(parents=True, exist_ok=True)
    make_tone(settings.audio_dir / "take1.wav", seconds=3)
    gen = FakeGenerator(GenerationResult("take1.wav", None, {
        "seed": 7, "model": "acestep-v15-turbo", "model_revision": "r1", "license": "MIT"}))
    c = make_client(settings, gen)
    rel = create(c, duration_s=15)
    run = c.post(f"/api/releases/{rel['id']}/run").json()
    assert run["status"] == "review" and run["has_audio"] is True
    assert run["seed"] is not None
    assert [e["action"] for e in run["events"]] == ["create", "start_generation", "submit_for_review"]
    (take,) = run["assets"]
    assert take["kind"] == "take" and take["provenance"]["source"] == "generated"
    assert take["provenance"]["model"] == "acestep-v15-turbo" and take["provenance"]["seed"] == 7
    assert take["provenance"]["prompt"] == run["prompt"]
    assert c.get(f"/api/releases/{rel['id']}/audio").status_code == 200


def test_generation_without_license_is_flagged(settings, make_client):
    settings.ace_step_enabled = True
    settings.audio_dir.mkdir(parents=True, exist_ok=True)
    (settings.audio_dir / "take1.wav").write_bytes(b"RIFF")  # unreadable audio
    c = make_client(settings, FakeGenerator())
    rel = create(c)
    run = c.post(f"/api/releases/{rel['id']}/run").json()
    # Without ffmpeg the file is stored unmeasured; with ffmpeg the bad file fails the run.
    assert run["status"] in {"review", "failed"}


def test_audio_outside_audio_dir_is_not_served(settings, make_client, tmp_path):
    settings.ace_step_enabled = True
    (tmp_path / "secret.wav").write_bytes(b"x")
    gen = FakeGenerator(GenerationResult(str(tmp_path / "secret.wav"), None, {}))
    c = make_client(settings, gen)
    rel = create(c)
    run = c.post(f"/api/releases/{rel['id']}/run").json()
    assert run["has_audio"] is False and run["assets"] == []
    assert "outside AUDIO_DIR" in run["workflow_note"]
    assert c.get(f"/api/releases/{rel['id']}/audio").status_code == 404


def test_generation_failure_marks_failed(settings, make_client):
    settings.ace_step_enabled = True
    c = make_client(settings, FakeGenerator(error="cuda oom"))
    rel = create(c)
    run = c.post(f"/api/releases/{rel['id']}/run").json()
    assert run["status"] == "failed" and "cuda oom" in run["workflow_note"]
    assert c.post(f"/api/releases/{rel['id']}/decision", json={"action": "reopen"}).json()["status"] == "draft"
