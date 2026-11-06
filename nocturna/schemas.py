from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import ReleaseStatus

Actor = Field(default="", max_length=100)


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    tags: str = Field(default="", max_length=600)
    bpm_min: int | None = Field(default=None, ge=40, le=200)
    bpm_max: int | None = Field(default=None, ge=40, le=200)
    default_key: str | None = Field(default=None, max_length=20)
    active: bool = True

    @model_validator(mode="after")
    def _range(self):
        if self.bpm_min and self.bpm_max and self.bpm_min > self.bpm_max:
            raise ValueError("bpm_min must not exceed bpm_max")
        return self


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    tags: str | None = Field(default=None, max_length=600)
    bpm_min: int | None = Field(default=None, ge=40, le=200)
    bpm_max: int | None = Field(default=None, ge=40, le=200)
    default_key: str | None = Field(default=None, max_length=20)
    active: bool | None = None


class TemplateOut(TemplateCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ReleaseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    lane: str = Field(default="", max_length=100)
    brief: str = Field(default="", max_length=2000)
    bpm: int | None = Field(default=None, ge=40, le=200)
    musical_key: str | None = Field(default=None, max_length=20)
    duration_s: int = Field(default=180, ge=15, le=900)
    template_id: int | None = None
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)


class ReleaseUpdate(BaseModel):
    # Content fields: only while draft/rejected/failed.
    lane: str | None = Field(default=None, max_length=100)
    brief: str | None = Field(default=None, max_length=2000)
    bpm: int | None = Field(default=None, ge=40, le=200)
    musical_key: str | None = Field(default=None, max_length=20)
    duration_s: int | None = Field(default=None, ge=15, le=900)
    template_id: int | None = None
    seed: int | None = Field(default=None, ge=0, le=2**32 - 1)
    # Metadata fields: also editable during review.
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    credits: str | None = Field(default=None, max_length=2000)
    tags: str | None = Field(default=None, max_length=500)


METADATA_FIELDS = {"title", "description", "credits", "tags"}


class Decision(BaseModel):
    action: Literal["approve", "reject", "reopen"]
    note: str = Field(default="", max_length=2000)
    actor: str = Actor


class Comment(BaseModel):
    note: str = Field(min_length=1, max_length=2000)
    actor: str = Actor


class ChecklistUpdate(BaseModel):
    items: dict[str, bool]
    actor: str = Actor


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    action: str
    from_status: str | None
    to_status: str
    note: str
    actor: str
    created_at: datetime


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    path: str
    original_name: str | None
    sha256: str
    size_bytes: int
    parent_id: int | None
    codec: str | None
    duration_s: float | None
    sample_rate: int | None
    channels: int | None
    bit_depth: int | None
    integrated_lufs: float | None
    loudness_range_lu: float | None
    true_peak_dbtp: float | None
    sample_peak_dbfs: float | None
    width: int | None
    height: int | None
    qc_warnings: list[str]
    provenance: dict
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
    template_id: int | None
    seed: int | None
    prompt: str | None
    status: ReleaseStatus
    audio_path: str | None
    audio_url: str | None
    workflow_note: str | None
    description: str
    credits: str
    tags: str
    checklist: dict[str, bool]
    created_at: datetime
    updated_at: datetime
    has_audio: bool = False


class ReleaseDetail(ReleaseOut):
    events: list[EventOut] = []
    assets: list[AssetOut] = []
    approval_blockers: list[str] = []
