"""Search Freesound for human-recorded sounds that Nocturna may use commercially.

Only CC0 and CC BY sounds are returned as usable; NC and Sampling+ sounds are marked blocked.
Imports use Freesound's high-quality MP3 preview, which needs only an API key. Full-quality
originals need OAuth2 and are not downloaded here.
Docs: https://freesound.org/docs/api/
"""

from dataclasses import dataclass

import httpx

API = "https://freesound.org/apiv2"
FIELDS = "id,name,username,license,url,previews,duration,tags"


class FreesoundError(RuntimeError):
    pass


def licence_from_url(url: str) -> str | None:
    """Map a Freesound licence URL to a usable licence name, or None if not allowed."""
    u = (url or "").lower()
    if "publicdomain/zero" in u:
        return "CC0 1.0"
    if "/licenses/by/" in u:
        version = u.rstrip("/").rsplit("/", 1)[-1]
        return f"CC BY {version}" if version[:1].isdigit() else "CC BY"
    return None  # by-nc, sampling+, anything else


@dataclass
class Sound:
    id: int
    name: str
    username: str
    licence_url: str
    licence: str | None
    url: str
    preview_url: str | None
    duration_s: float | None

    @property
    def usable(self) -> bool:
        return self.licence is not None

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "username": self.username,
                "license": self.licence, "license_url": self.licence_url, "usable": self.usable,
                "url": self.url, "preview_url": self.preview_url, "duration_s": self.duration_s}


def _sound(data: dict) -> Sound:
    previews = data.get("previews") or {}
    return Sound(
        id=int(data["id"]), name=data.get("name", ""), username=data.get("username", ""),
        licence_url=data.get("license", ""), licence=licence_from_url(data.get("license", "")),
        url=data.get("url", ""), preview_url=previews.get("preview-hq-mp3"),
        duration_s=data.get("duration"),
    )


class Freesound:
    def __init__(self, api_key: str, client: httpx.Client | None = None):
        if not api_key:
            raise FreesoundError("set FREESOUND_API_KEY (free at https://freesound.org/apiv2/apply)")
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=30, follow_redirects=True)

    def _get(self, path: str, **params) -> dict:
        try:
            r = self.client.get(f"{API}{path}", params={**params, "token": self.api_key})
        except httpx.HTTPError as exc:
            raise FreesoundError(f"Freesound unreachable: {exc}") from exc
        if r.status_code != 200:
            raise FreesoundError(f"Freesound returned {r.status_code}")
        return r.json()

    def search(self, query: str, page_size: int = 20) -> list[Sound]:
        data = self._get("/search/text/", query=query, fields=FIELDS, page_size=page_size)
        return [_sound(d) for d in data.get("results", [])]

    def sound(self, sound_id: int) -> Sound:
        return _sound(self._get(f"/sounds/{int(sound_id)}/", fields=FIELDS))

    def download_preview(self, sound: Sound, dest, max_bytes: int) -> None:
        if not sound.preview_url:
            raise FreesoundError("this sound has no preview to download")
        written = 0
        try:
            with self.client.stream("GET", sound.preview_url) as r, open(dest, "wb") as out:
                if r.status_code != 200:
                    raise FreesoundError(f"preview download returned {r.status_code}")
                for chunk in r.iter_bytes():
                    written += len(chunk)
                    if written > max_bytes:
                        raise FreesoundError("preview is larger than the upload limit")
                    out.write(chunk)
        except httpx.HTTPError as exc:
            raise FreesoundError(f"preview download failed: {exc}") from exc
