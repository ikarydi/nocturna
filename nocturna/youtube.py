"""Scheduled YouTube uploads through the YouTube Data API v3.

Every upload is created PRIVATE with a future `publishAt`, so nothing goes public before its
slot and J can still pull it in YouTube Studio. Every upload sets
`status.containsSyntheticMedia = true` (YouTube's altered or synthetic content disclosure),
and that cannot be turned off here.

One-time setup (see docs/youtube.md):

    pip install -e '.[youtube]'
    python -m nocturna.youtube auth     # opens Google sign-in, stores data/youtube-token.json

Quota (checked 2026-11-18): videos.insert costs 1 unit from a separate bucket of 100 uploads
a day; thumbnails.set and playlistItems.insert cost 50 units each from the 10,000 daily units.
"""

import os
import re
import sys
from collections.abc import Iterable
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",  # playlists
]
MUSIC_CATEGORY = "10"
DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
AI_DISCLOSURE_LINE = (
    "Made with generative AI (ACE-Step) and a human layer of real recordings; "
    "curated, edited and approved by a human."
)


class YouTubeError(RuntimeError):
    pass


# ------------------------------------------------------------------ schedule


def parse_slots(spec: str) -> list[tuple[int, time]]:
    slots = []
    for part in filter(None, (p.strip().lower() for p in spec.split(","))):
        m = re.fullmatch(r"(mon|tue|wed|thu|fri|sat|sun)\s+(\d{1,2}):(\d{2})", part)
        if not m:
            raise YouTubeError(f"bad slot {part!r}; use e.g. 'tue 20:00'")
        slots.append((DAYS[m.group(1)], time(int(m.group(2)), int(m.group(3)))))
    if not slots:
        raise YouTubeError("no publish slots configured")
    return sorted(slots)


def next_slot(spec: str, tz: str, now: datetime, taken: Iterable[datetime],
              min_lead_hours: int = 12) -> datetime:
    """The earliest free weekly slot at least `min_lead_hours` from now, in UTC."""
    zone = ZoneInfo(tz)
    slots = parse_slots(spec)
    earliest = now.astimezone(zone) + timedelta(hours=min_lead_hours)
    busy = {t.astimezone(UTC).replace(second=0, microsecond=0) for t in taken}
    day0 = earliest.date()
    for offset in range(7 * 52):
        day = day0 + timedelta(days=offset)
        for weekday, at in slots:
            if day.weekday() != weekday:
                continue
            local = datetime.combine(day, at, tzinfo=zone)
            if local < earliest:
                continue
            utc = local.astimezone(UTC)
            if utc not in busy:
                return utc
    raise YouTubeError("no free slot in the next year")


# ------------------------------------------------------------------ metadata


def normalise_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def build_body(*, title: str, description: str, tags: list[str], publish_at: datetime,
               kind: str) -> dict:
    if kind == "short" and "#shorts" not in title.lower():
        title = f"{title} #shorts"
    return {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": [t for t in tags if t][:30],
            "categoryId": MUSIC_CATEGORY,
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "containsSyntheticMedia": True,
            "selfDeclaredMadeForKids": False,
            "embeddable": True,
        },
    }


def description_for(release, human_credits: list[str]) -> str:
    parts = [release.description.strip()] if release.description.strip() else []
    meta = " · ".join(x for x in [
        release.catalog_no, f"captured {release.capture_time}" if release.capture_time else "",
        f"{release.bpm} BPM" if release.bpm else "", release.musical_key or "",
        release.lane or "",
    ] if x)
    parts.append(meta)
    credits = [c for c in [release.credits.strip(), *human_credits] if c]
    if credits:
        parts.append("Credits\n" + "\n".join(credits))
    parts.append(AI_DISCLOSURE_LINE)
    return "\n\n".join(parts)


# ------------------------------------------------------------------ uploader


class Uploader(Protocol):
    def upload(self, video: Path, body: dict) -> str: ...
    def set_thumbnail(self, video_id: str, image: Path) -> None: ...
    def ensure_playlist(self, title: str) -> str: ...
    def add_to_playlist(self, playlist_id: str, video_id: str) -> None: ...


class GoogleUploader:
    """The real uploader. Needs the `youtube` extra and a stored OAuth token."""

    def __init__(self, token_path: Path):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise YouTubeError("install the YouTube extra: pip install -e '.[youtube]'") from exc
        if not token_path.is_file():
            raise YouTubeError(f"no YouTube token at {token_path}; run python -m nocturna.youtube auth")
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if not creds.valid and creds.refresh_token:
            creds.refresh(Request())
            _save_token(token_path, creds.to_json())
        self.api = build("youtube", "v3", credentials=creds, cache_discovery=False)
        self._playlists: dict[str, str] = {}

    def upload(self, video: Path, body: dict) -> str:
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        media = MediaFileUpload(str(video), mimetype="video/mp4", chunksize=8 << 20, resumable=True)
        request = self.api.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        try:
            while response is None:
                _, response = request.next_chunk(num_retries=3)
        except HttpError as exc:
            raise YouTubeError(f"upload failed: {exc}") from exc
        return response["id"]

    def set_thumbnail(self, video_id: str, image: Path) -> None:
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        try:
            self.api.thumbnails().set(
                videoId=video_id, media_body=MediaFileUpload(str(image), mimetype="image/jpeg")
            ).execute()
        except HttpError as exc:
            # Custom thumbnails need a phone-verified channel; the upload itself still stands.
            raise YouTubeError(f"thumbnail not set (is the channel verified?): {exc}") from exc

    def ensure_playlist(self, title: str) -> str:
        if title in self._playlists:
            return self._playlists[title]
        token = None
        while True:
            page = self.api.playlists().list(part="snippet", mine=True, maxResults=50,
                                             pageToken=token).execute()
            for item in page.get("items", []):
                self._playlists[item["snippet"]["title"]] = item["id"]
            token = page.get("nextPageToken")
            if not token:
                break
        if title not in self._playlists:
            created = self.api.playlists().insert(part="snippet,status", body={
                "snippet": {"title": title, "description": f"Nocturna · {title}"},
                "status": {"privacyStatus": "public"},
            }).execute()
            self._playlists[title] = created["id"]
        return self._playlists[title]

    def add_to_playlist(self, playlist_id: str, video_id: str) -> None:
        self.api.playlistItems().insert(part="snippet", body={"snippet": {
            "playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id},
        }}).execute()


def _save_token(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data)
    os.chmod(path, 0o600)


def auth(client_secrets: Path, token_path: Path) -> None:
    """Run Google's installed-app OAuth flow and store the token locally."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise YouTubeError("install the YouTube extra: pip install -e '.[youtube]'") from exc
    if not client_secrets.is_file():
        raise YouTubeError(
            f"save your OAuth client (Desktop app) JSON from Google Cloud Console to {client_secrets}"
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES)
    # WSL2 forwards localhost to Windows, so the browser on Windows can complete the redirect.
    creds = flow.run_local_server(port=8765, open_browser=False,
                                  authorization_prompt_message="Open this URL to sign in:\n{url}")
    _save_token(token_path, creds.to_json())
    print(f"Saved YouTube token to {token_path} (keep it private; it is git-ignored).")


def main(argv: list[str]) -> int:
    from .config import get_settings

    if argv[:1] != ["auth"]:
        print("usage: python -m nocturna.youtube auth")
        return 2
    s = get_settings()
    try:
        auth(s.youtube_client_secrets, s.youtube_token_path)
    except YouTubeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
