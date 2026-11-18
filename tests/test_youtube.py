from datetime import UTC, datetime

import pytest

from nocturna import youtube
from nocturna.models import CHECKLIST_ITEMS

from .conftest import make_tone, needs_ffmpeg
from .test_api import to_review, upload

TZ = "Europe/Budapest"


class FakeUploader:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def upload(self, video, body):
        if self.fail:
            raise youtube.YouTubeError("quotaExceeded")
        assert video.is_file() and video.stat().st_size > 0
        self.calls.append(("upload", video.name, body))
        return f"vid{len(self.calls)}"

    def set_thumbnail(self, video_id, image):
        self.calls.append(("thumbnail", video_id, image.suffix))

    def ensure_playlist(self, title):
        self.calls.append(("playlist", title))
        return "PL1"

    def add_to_playlist(self, playlist_id, video_id):
        self.calls.append(("add", playlist_id, video_id))


def test_slots_respect_lead_time_and_taken():
    now = datetime(2026, 11, 18, 5, 0, tzinfo=UTC)  # Wed 06:00 Budapest
    first = youtube.next_slot("tue 20:00,fri 20:00", TZ, now, [], 12)
    assert first == datetime(2026, 11, 20, 19, 0, tzinfo=UTC)  # Fri 20:00 CET
    second = youtube.next_slot("tue 20:00,fri 20:00", TZ, now, [first], 12)
    assert second == datetime(2026, 11, 24, 19, 0, tzinfo=UTC)  # next Tue
    # Too close: Fri 20:00 with a 72 h lead moves to Tuesday.
    assert youtube.next_slot("tue 20:00,fri 20:00", TZ, now, [], 72) == second
    with pytest.raises(youtube.YouTubeError):
        youtube.parse_slots("someday 25:00")


def test_body_is_private_scheduled_and_disclosed():
    at = datetime(2026, 11, 20, 19, 0, tzinfo=UTC)
    body = youtube.build_body(title="Ashes", description="d", tags=["afro house", ""],
                              publish_at=at, kind="short")
    assert body["status"] == {"privacyStatus": "private", "publishAt": "2026-11-20T19:00:00Z",
                              "containsSyntheticMedia": True, "selfDeclaredMadeForKids": False,
                              "embeddable": True}
    assert body["snippet"]["title"] == "Ashes #shorts" and body["snippet"]["tags"] == ["afro house"]
    assert body["snippet"]["categoryId"] == "10"


def approved_release(c, tmp_path, title="Ashes Over Vesper"):
    rid = to_review(c, title=title, duration_s=15, bpm=120)["id"]
    assert upload(c, rid, make_tone(tmp_path / "take.wav", seconds=15, volume=0.2)).status_code == 201
    r = upload(c, rid, make_tone(tmp_path / "rain.wav", seconds=3, volume=0.1), kind="human",
               source_type="freesound", license="CC BY 4.0", author="nightrec",
               sound_title="Rain", source_url="https://freesound.org/s/1/")
    assert r.status_code == 201, r.text
    assert c.post(f"/api/releases/{rid}/export").status_code == 200
    assert c.post(f"/api/releases/{rid}/cover").status_code == 200
    c.put(f"/api/releases/{rid}/checklist", json={"items": {k: True for k in CHECKLIST_ITEMS}})
    return rid


@needs_ffmpeg
def test_schedule_and_upload(settings, make_client, tmp_path):
    settings.youtube_enabled = True
    fake = FakeUploader()
    from fastapi.testclient import TestClient
    from nocturna.api import create_app
    with TestClient(create_app(settings, uploader_factory=lambda: fake)) as c:
        rid = approved_release(c, tmp_path)
        # Not approved yet: refused.
        assert c.post(f"/api/releases/{rid}/youtube", json={}).status_code == 409
        r = c.post(f"/api/releases/{rid}/decision", json={"action": "approve", "actor": "J"})
        assert r.status_code == 200, r.text
        r = c.post(f"/api/releases/{rid}/youtube", json={"actor": "J"})
        assert r.status_code == 201, r.text
        assert sorted(u["kind"] for u in r.json()) == ["long", "short"]

        uploads = {u["kind"]: u for u in c.get("/api/youtube/uploads").json()}
        assert uploads["long"]["status"] == "scheduled", uploads["long"]["error"]
        assert uploads["short"]["status"] == "scheduled"
        bodies = [call[2] for call in fake.calls if call[0] == "upload"]
        assert all(b["status"]["containsSyntheticMedia"] is True for b in bodies)
        assert all(b["status"]["privacyStatus"] == "private" for b in bodies)
        long_body = next(b for b in bodies if "#shorts" not in b["snippet"]["title"])
        assert "Rain\" by nightrec" in long_body["snippet"]["description"]
        assert "generative AI" in long_body["snippet"]["description"]
        assert ("playlist", "dark ambient") in fake.calls
        assert sum(1 for call in fake.calls if call[0] == "thumbnail") == 1  # long only

        # Booking again does nothing new; history records the uploads.
        assert c.post(f"/api/releases/{rid}/youtube", json={}).json() == []
        actions = [e["action"] for e in c.get(f"/api/releases/{rid}").json()["events"]]
        assert actions.count("youtube_upload") == 2


@needs_ffmpeg
def test_auto_schedule_on_approve_and_failure_is_recorded(settings, make_client, tmp_path):
    settings.youtube_enabled = True
    settings.youtube_auto_schedule = True
    settings.youtube_shorts = False
    from fastapi.testclient import TestClient
    from nocturna.api import create_app
    with TestClient(create_app(settings, uploader_factory=lambda: FakeUploader(fail=True))) as c:
        rid = approved_release(c, tmp_path)
        c.post(f"/api/releases/{rid}/decision", json={"action": "approve", "actor": "J"})
        (u,) = c.get("/api/youtube/uploads").json()
        assert u["kind"] == "long" and u["status"] == "failed" and "quotaExceeded" in u["error"]
        assert c.post(f"/api/youtube/uploads/{u['id']}/retry").status_code == 200


@needs_ffmpeg
def test_disabled_and_duplicate_titles_refused(settings, make_client, tmp_path):
    from fastapi.testclient import TestClient
    from nocturna.api import create_app
    with TestClient(create_app(settings, uploader_factory=FakeUploader)) as c:
        rid = approved_release(c, tmp_path)
        c.post(f"/api/releases/{rid}/decision", json={"action": "approve"})
        r = c.post(f"/api/releases/{rid}/youtube", json={})
        assert r.status_code == 409 and "off" in r.json()["detail"]
    settings.youtube_enabled = True
    with TestClient(create_app(settings, uploader_factory=FakeUploader)) as c:
        assert c.post(f"/api/releases/{rid}/youtube", json={"kinds": ["long"]}).status_code == 201
        rid2 = approved_release(c, tmp_path, title="ashes over  VESPER")
        c.post(f"/api/releases/{rid2}/decision", json={"action": "approve"})
        r = c.post(f"/api/releases/{rid2}/youtube", json={})
        assert r.status_code == 409 and "already titled" in r.json()["detail"]
