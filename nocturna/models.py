from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class ReleaseStatus(str, enum.Enum):
    draft = "draft"
    generating = "generating"
    review = "review"
    approved = "approved"
    rejected = "rejected"
    failed = "failed"


CHECKLIST_ITEMS: dict[str, str] = {
    "originality": "Listened in full; no recognizable melody, hook or sample from existing work",
    "no_imitation": "Prompt and result do not imitate a named artist or track",
    "rights": "Model, checkpoint and license recorded and verified for commercial use",
    "audio_qc": "Loudness, peaks and duration reviewed; no clipping or artifacts",
    "artwork": "Artwork is original or licensed, and crops cleanly to 16:9 and square",
    "metadata": "Title, description, credits and tags are complete and accurate",
    "ai_disclosure": "YouTube 'altered or synthetic content' disclosure will be set on upload",
    "distinct": "Distinct from recent releases (not templated or mass-produced)",
}


class PromptTemplate(Base):
    """An editable musical lane: shared tags and constraints for a family of releases."""

    __tablename__ = "prompt_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="")
    bpm_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bpm_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_key: Mapped[str | None] = mapped_column(String(20), nullable=True)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Release(Base):
    __tablename__ = "releases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    lane: Mapped[str] = mapped_column(String(100), default="")
    brief: Mapped[str] = mapped_column(Text, default="")
    bpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    musical_key: Mapped[str | None] = mapped_column(String(20), nullable=True)
    duration_s: Mapped[int] = mapped_column(Integer, default=180)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ReleaseStatus] = mapped_column(
        Enum(ReleaseStatus, name="release_status", native_enum=False, length=20),
        default=ReleaseStatus.draft,
        index=True,
    )
    audio_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    audio_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    workflow_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("prompt_templates.id", ondelete="SET NULL"), nullable=True
    )
    seed: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Release metadata for the eventual (manual) upload.
    description: Mapped[str] = mapped_column(Text, default="")
    credits: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="")
    checklist: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    events: Mapped[list[ReleaseEvent]] = relationship(
        back_populates="release", cascade="all, delete-orphan", order_by="ReleaseEvent.id"
    )
    assets: Mapped[list[Asset]] = relationship(
        back_populates="release", cascade="all, delete-orphan", order_by="Asset.id"
    )
    template: Mapped[PromptTemplate | None] = relationship()

    def latest_asset(self, kind: str) -> Asset | None:
        matches = [a for a in self.assets if a.kind == kind]
        return matches[-1] if matches else None

    def checklist_missing(self) -> list[str]:
        done = self.checklist or {}
        return [key for key in CHECKLIST_ITEMS if not done.get(key)]


class Asset(Base):
    """A file belonging to a release, with how it was made and what it measures."""

    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id", ondelete="CASCADE"), index=True)
    # take (raw generated/uploaded audio), master (lossless), delivery (loudness-normalized), artwork
    kind: Mapped[str] = mapped_column(String(20))
    path: Mapped[str] = mapped_column(String(500))  # relative to AUDIO_DIR
    original_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    # Measurements (audio only; null when ffmpeg is unavailable or for artwork)
    codec: Mapped[str | None] = mapped_column(String(40), nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bit_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    integrated_lufs: Mapped[float | None] = mapped_column(Float, nullable=True)
    loudness_range_lu: Mapped[float | None] = mapped_column(Float, nullable=True)
    true_peak_dbtp: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_peak_dbfs: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    qc_warnings: Mapped[list] = mapped_column(JSON, default=list)
    # How it was made: source (generated|uploaded|derived), model, model_revision, license,
    # seed, prompt, settings, tool versions.
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    release: Mapped[Release] = relationship(back_populates="assets")


class ReleaseEvent(Base):
    """Append-only history of every status change and reviewer decision."""

    __tablename__ = "release_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(40))
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    release: Mapped[Release] = relationship(back_populates="events")
