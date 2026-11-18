"""From an approved release to scheduled, private YouTube uploads.

schedule() only books slots and writes `youtube_uploads` rows (fast, in the request).
process() renders the video files and talks to YouTube (slow, in the background).
"""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import assets, human, video, youtube
from .config import Settings
from .models import Release, ReleaseEvent, ReleaseStatus, YouTubeUpload

KINDS = ("long", "short")
ACTIVE = ("queued", "uploading", "scheduled")


class PublishError(ValueError):
    pass


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def schedule(db: Session, release: Release, settings: Settings, *, kinds: list[str] | None = None,
             actor: str = "", now: datetime | None = None) -> list[YouTubeUpload]:
    if not settings.youtube_enabled:
        raise PublishError("YouTube uploads are off (set YOUTUBE_ENABLED=true after auth)")
    if release.status != ReleaseStatus.approved:
        raise PublishError("only approved releases can be scheduled")
    kinds = kinds or (list(KINDS) if settings.youtube_shorts else ["long"])
    unknown = set(kinds) - set(KINDS)
    if unknown:
        raise PublishError(f"unknown upload kinds: {sorted(unknown)}")
    if release.latest_asset("delivery") is None or release.latest_asset("artwork") is None:
        raise PublishError("needs a delivery file and artwork (make a cover first)")

    # Distinctness: no other release on the channel may share this title.
    normalise = youtube.normalise_title(release.title)
    others = db.execute(
        select(Release.title).join(YouTubeUpload).where(
            Release.id != release.id, YouTubeUpload.status.in_(ACTIVE))
    ).scalars().all()
    if any(youtube.normalise_title(t) == normalise for t in others):
        raise PublishError(f"another release on the channel is already titled {release.title!r}")

    now = now or datetime.now(UTC)
    created = []
    for kind in kinds:
        if any(u.kind == kind and u.status in ACTIVE for u in release.uploads):
            continue  # already booked
        taken = db.execute(
            select(YouTubeUpload.publish_at).where(
                YouTubeUpload.kind == kind, YouTubeUpload.status.in_(ACTIVE))
        ).scalars().all()
        spec = settings.youtube_long_slots if kind == "long" else settings.youtube_short_slots
        at = youtube.next_slot(spec, settings.youtube_timezone, now, map(_aware, taken),
                               settings.youtube_min_lead_hours)
        upload = YouTubeUpload(kind=kind, status="queued", publish_at=at, actor=actor,
                               title=release.title)
        release.uploads.append(upload)
        status = release.status.value
        release.events.append(ReleaseEvent(
            action="youtube_schedule", from_status=status, to_status=status, actor=actor,
            note=f"{kind} booked for {at.astimezone(UTC).isoformat()} (private until then)",
        ))
        created.append(upload)
    db.flush()
    return created


def process(db: Session, upload: YouTubeUpload, media_root: Path,
            make_uploader: Callable[[], youtube.Uploader]) -> YouTubeUpload:
    release = upload.release
    upload.status, upload.error = "uploading", None
    db.commit()
    try:
        cover = assets.resolve(media_root, release.latest_asset("artwork").path)
        delivery_asset = release.latest_asset("delivery")
        audio_path = assets.resolve(media_root, delivery_asset.path)
        if cover is None or audio_path is None:
            raise PublishError("artwork or delivery file is missing on disk")
        folder = assets.release_dir(media_root, release) / "youtube"
        base = assets.safe_name(release.title).lower()
        if upload.kind == "long":
            out = folder / f"{base}-1080p.mp4"
            video.render_long(cover, audio_path, out)
        else:
            out = folder / f"{base}-short.mp4"
            video.render_short(cover, audio_path, out, delivery_asset.duration_s or release.duration_s)
        body = youtube.build_body(
            title=release.title,
            description=youtube.description_for(release, human.credits(release.assets)),
            tags=[t.strip() for t in release.tags.split(",")],
            publish_at=_aware(upload.publish_at), kind=upload.kind,
        )
        uploader = make_uploader()
        upload.video_id = uploader.upload(out, body)
        notes = []
        if upload.kind == "long":
            thumb = folder / f"{base}-thumb.jpg"
            video.make_thumbnail(cover, thumb)
            try:
                uploader.set_thumbnail(upload.video_id, thumb)
            except youtube.YouTubeError as exc:
                notes.append(str(exc))
        try:
            playlist = uploader.ensure_playlist(release.lane or "Nocturna")
            uploader.add_to_playlist(playlist, upload.video_id)
        except youtube.YouTubeError as exc:
            notes.append(str(exc))
        upload.status = "scheduled"
        upload.error = "; ".join(notes) or None
        note = f"{upload.kind} uploaded as private, video {upload.video_id}, AI disclosure set"
    except Exception as exc:  # noqa: BLE001 - every failure is recorded on the upload row
        db.rollback()
        upload.status, upload.error = "failed", str(exc)[:2000]
        note = f"{upload.kind} upload failed: {upload.error}"
    status = release.status.value
    release.events.append(ReleaseEvent(action="youtube_upload", from_status=status,
                                       to_status=status, note=note, actor=upload.actor))
    db.commit()
    return upload
