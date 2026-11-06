from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    events: Mapped[list[ReleaseEvent]] = relationship(
        back_populates="release", cascade="all, delete-orphan", order_by="ReleaseEvent.id"
    )


class ReleaseEvent(Base):
    """Append-only history of every status change and reviewer decision."""

    __tablename__ = "release_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(40))
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    release: Mapped[Release] = relationship(back_populates="events")
