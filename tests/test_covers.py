from PIL import Image

from nocturna import covers

from .test_api import to_review


def test_render_is_deterministic(tmp_path):
    text = covers.CoverText("NCT-0007", "03:17", "Ashes Over Vesper", "52 BPM · D minor")
    a, b, c = tmp_path / "a.png", tmp_path / "b.png", tmp_path / "c.png"
    covers.render(text, 1, a, size=600)
    covers.render(text, 1, b, size=600)
    covers.render(text, 2, c, size=600)
    assert a.read_bytes() == b.read_bytes() and a.read_bytes() != c.read_bytes()
    with Image.open(a) as img:
        assert img.size == (600, 600)
        # Mostly night: the median pixel is near-black.
        small = img.convert("RGB").resize((50, 50))
        px = sorted(sum(small.getpixel((x, y))) for x in range(50) for y in range(50))
        assert px[len(px) // 2] < 120


def test_capture_time_is_night():
    for seed in range(50):
        hh, mm = map(int, covers.capture_time_for(seed).split(":"))
        assert 0 <= hh <= 5 and 0 <= mm <= 59


def test_cover_endpoint_and_card(client):
    rid = to_review(client, bpm=52, musical_key="D minor")["id"]
    r = client.post(f"/api/releases/{rid}/cover", params={"actor": "J"})
    assert r.status_code == 200, r.text
    rel = r.json()
    art = rel["assets"][-1]
    assert art["kind"] == "artwork" and art["provenance"]["generator"] == covers.VERSION
    assert rel["capture_time"] and rel["catalog_no"] == f"NCT-{rid:04d}"
    card = client.get(f"/api/releases/{rid}/card").text
    assert card.startswith(f"NCT-{rid:04d} · ASHES OVER VESPER")
    assert "HUMAN LAYER   none yet" in card and "Infrared Archive cover" in card
    # Capture time can be set by hand during review.
    assert client.patch(f"/api/releases/{rid}", json={"capture_time": "04:02"}).json()["capture_time"] == "04:02"
    assert client.patch(f"/api/releases/{rid}", json={"capture_time": "25:00"}).status_code == 422
