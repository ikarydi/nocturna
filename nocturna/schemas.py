from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import ReleaseStatus


class ReleaseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    lane: str = Field(default="", max_length=100)
    brief: str = Field(default="", max_length=2000)
    bpm: int | None = Field(default=None, ge=40, le=200)
    musical_key: str | None = Field(default=None, max_length=20)
    duration_s: int = Field(default=180, ge=15, le=900)


class ReleaseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    lane: str | None = Field(default=None, max_length=100)
    brief: str | None = Field(default=None, max_length=2000)
    bpm: int | None = Field(default=None, ge=40, le=200)
    musical_key: str | None = Field(default=None, max_length=20)
    duration_s: int | None = Field(default=None, ge=15, le=900)


class Decision(BaseModel):
    action: Literal["approve", "reject", "reopen"]
    note: str = Field(default="", max_length=2000)


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    action: str
    from_status: str | None
    to_status: str
    note: str
    created_at: datetime


class ReleaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    lane: str
    brief: str
    bpm: int | None
    musical_key: str | None
    duration_s: int
    prompt: str | None
    status: ReleaseStatus
    audio_path: str | None
    audio_url: str | None
    workflow_note: str | None
    created_at: datetime
    updated_at: datetime
    has_audio: bool = False


class ReleaseDetail(ReleaseOut):
    events: list[EventOut] = []
