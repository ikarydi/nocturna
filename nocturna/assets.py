"""Storing, measuring and deriving release assets, with provenance on every file."""

import re
import shutil
from pathlib import Path
from typing import BinaryIO

from sqlalchemy.orm import Session

from . import audio
from .models import Asset, Release

AUDIO_EXTS = {".wav", ".flac", ".mp3", ".aiff", ".aif", ".ogg", ".m4a"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
UPLOAD_KINDS = {"take": AUDIO_EXTS, "artwork": IMAGE_EXTS}


class AssetError(ValueError):
    pass


def safe_name(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name).name).strip("-.")
    return stem[:120] or "file"


def release_dir(media_root: Path, release: Release) -> Path:
    path = media_root / "releases" / str(release.id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve(media_root: Path, rel_path: str) -> Path | None:
    """Resolve a stored path, refusing anything outside the media root."""
    path = Path(rel_path)
    path = (path if path.is_absolute() else media_root / path).resolve()
    if not path.is_relative_to(media_root) or not path.is_file():
        return None
    return path


def _measure(asset: Asset, path: Path, expected_duration_s: int | None) -> None:
    if not audio.ffmpeg_available():
        asset.qc_warnings = ["not measured: ffmpeg is not installed"]
        return
    try:
        if asset.kind == "artwork":
            info = audio.inspect_image(path)
        else:
            info = audio.inspect_audio(path, expected_duration_s)
    except audio.AudioError as exc:
        raise AssetError(str(exc)) from exc
    for key, value in info.as_dict().items():
        setattr(asset, key, value)


def register(
    db: Session,
    media_root: Path,
    release: Release,
    *,
    kind: str,
    path: Path,
    provenance: dict,
    original_name: str | None = None,
    parent: Asset | None = None,
) -> Asset:
    asset = Asset(
        kind=kind,
        path=str(path.relative_to(media_root)),
        original_name=original_name,
        sha256=audio.sha256_file(path),
        size_bytes=path.stat().st_size,
        parent_id=parent.id if parent else None,
        provenance=provenance,
        qc_warnings=[],
    )
    _measure(asset, path, release.duration_s if kind == "take" else None)
    release.assets.append(asset)
    db.flush()
    return asset


def save_upload(
    db: Session,
    media_root: Path,
    release: Release,
    *,
    kind: str,
    filename: str,
    stream: BinaryIO,
    max_bytes: int,
    provenance: dict,
) -> Asset:
    if kind not in UPLOAD_KINDS:
        raise AssetError(f"kind must be one of {sorted(UPLOAD_KINDS)}")
    ext = Path(filename).suffix.lower()
    if ext not in UPLOAD_KINDS[kind]:
        raise AssetError(f"{ext or 'no extension'} is not allowed for {kind}")
    n = len(release.assets) + 1
    dest = release_dir(media_root, release) / f"{kind}-{n:03d}-{safe_name(filename)}"
    written = 0
    try:
        with dest.open("wb") as out:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                written += len(chunk)
                if written > max_bytes:
                    raise AssetError(f"file is larger than {max_bytes // (1 << 20)} MB")
                out.write(chunk)
        if written == 0:
            raise AssetError("file is empty")
        return register(db, media_root, release, kind=kind, path=dest,
                        provenance=provenance, original_name=filename)
    except Exception:
        dest.unlink(missing_ok=True)
        raise


def adopt_generated(db: Session, media_root: Path, release: Release, audio_path: str,
                    provenance: dict) -> Asset | None:
    """Register a file the generator wrote into the media root as a take."""
    src = resolve(media_root, audio_path)
    if src is None:
        return None
    n = len(release.assets) + 1
    dest = release_dir(media_root, release) / f"take-{n:03d}-{safe_name(src.name)}"
    if src != dest:
        shutil.copy2(src, dest)
    return register(db, media_root, release, kind="take", path=dest,
                    provenance=provenance, original_name=src.name)


def export_masters(db: Session, media_root: Path, release: Release, *, target_lufs: float,
                   true_peak: float) -> tuple[Asset, Asset]:
    take = release.latest_asset("take")
    if take is None:
        raise AssetError("no take to export; upload or generate audio first")
    src = resolve(media_root, take.path)
    if src is None:
        raise AssetError("take file is missing on disk")
    if not audio.ffmpeg_available():
        raise AssetError("ffmpeg is not installed (run scripts/setup-wsl.sh)")
    folder = release_dir(media_root, release)
    base = safe_name(release.title).lower()
    master_path = folder / f"master-{take.id:03d}-{base}.flac"
    delivery_path = folder / f"delivery-{take.id:03d}-{base}.wav"
    tool = {"tool": "ffmpeg", "tool_version": audio.ffmpeg_version()}
    try:
        audio.export_master(src, master_path)
        master = register(db, media_root, release, kind="master", path=master_path, parent=take,
                          provenance={"source": "derived", "from_asset": take.id,
                                      "from_sha256": take.sha256, "process": "flac 24-bit lossless",
                                      **tool})
        settings = audio.export_delivery(master_path, delivery_path, target_lufs, true_peak)
        delivery = register(db, media_root, release, kind="delivery", path=delivery_path,
                            parent=master,
                            provenance={"source": "derived", "from_asset": master.id,
                                        "from_sha256": master.sha256,
                                        "process": "two-pass loudnorm", "settings": settings,
                                        **tool})
    except audio.AudioError as exc:
        raise AssetError(str(exc)) from exc
    return master, delivery
