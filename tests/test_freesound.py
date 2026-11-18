import httpx

from nocturna.freesound import Freesound, licence_from_url

from .conftest import needs_ffmpeg
from .test_api import to_review

SOUNDS = {
    1: {"id": 1, "name": "Rain on tin roof", "username": "nightrec",
        "license": "http://creativecommons.org/publicdomain/zero/1.0/",
        "url": "https://freesound.org/people/nightrec/sounds/1/",
        "previews": {"preview-hq-mp3": "https://cdn.freesound.org/previews/1.mp3"}, "duration": 12.0},
    2: {"id": 2, "name": "Cimbalom phrase", "username": "kay",
        "license": "https://creativecommons.org/licenses/by-nc/4.0/",
        "url": "https://freesound.org/people/kay/sounds/2/",
        "previews": {"preview-hq-mp3": "https://cdn.freesound.org/previews/2.mp3"}, "duration": 4.0},
}


def test_licence_from_url():
    assert licence_from_url("http://creativecommons.org/publicdomain/zero/1.0/") == "CC0 1.0"
    assert licence_from_url("https://creativecommons.org/licenses/by/4.0/") == "CC BY 4.0"
    assert licence_from_url("https://creativecommons.org/licenses/by-nc/4.0/") is None
    assert licence_from_url("http://creativecommons.org/licenses/sampling+/1.0/") is None


def fake_client(mp3: bytes = b"ID3fake"):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host in {"freesound.org", "cdn.freesound.org"}
        path = request.url.path
        if path.startswith("/apiv2/search/text/"):
            assert request.url.params["token"] == "k"
            return httpx.Response(200, json={"results": list(SOUNDS.values())})
        if path.startswith("/apiv2/sounds/"):
            return httpx.Response(200, json=SOUNDS[int(path.split("/")[3])])
        if path.startswith("/previews/"):
            return httpx.Response(200, content=mp3)
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_search_marks_usable(settings, make_client):
    c = make_client(settings)
    c.app.dependency_overrides = {}
    fs = Freesound("k", fake_client())
    sounds = fs.search("rain")
    assert [(s.id, s.usable) for s in sounds] == [(1, True), (2, False)]


def test_search_endpoint_without_key_is_503(client):
    r = client.get("/api/freesound/search", params={"q": "rain"})
    assert r.status_code == 503 and "FREESOUND_API_KEY" in r.json()["detail"]


@needs_ffmpeg
def test_import_cc0_and_refuse_nc(settings, make_client, tmp_path):
    import subprocess
    mp3 = tmp_path / "p.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "anoisesrc=d=3:a=0.05", "-ac", "2", "-ar", "44100", str(mp3)], check=True)
    from nocturna.api import create_app
    from fastapi.testclient import TestClient
    with TestClient(create_app(settings, freesound_client=Freesound("k", fake_client(mp3.read_bytes())))) as c:
        rid = to_review(c)["id"]
        assert [s["usable"] for s in c.get("/api/freesound/search", params={"q": "rain"}).json()] == [True, False]
        r = c.post(f"/api/releases/{rid}/human/freesound", json={"sound_id": 1, "actor": "J"})
        assert r.status_code == 201, r.text
        prov = r.json()["provenance"]
        assert prov["source_type"] == "freesound" and prov["license"] == "CC0 1.0"
        assert prov["freesound_id"] == 1
        r = c.post(f"/api/releases/{rid}/human/freesound", json={"sound_id": 2})
        assert r.status_code == 422 and "commercial" in r.json()["detail"]
        detail = c.get(f"/api/releases/{rid}").json()
        assert [a["kind"] for a in detail["assets"]] == ["human"]
        assert detail["human_credits"] == ['"Rain on tin roof" by nightrec via Freesound (CC0 1.0)']
