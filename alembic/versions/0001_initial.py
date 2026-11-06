"""initial release queue schema

Revision ID: 0001
Revises:
Create Date: 2026-11-06
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "releases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("lane", sa.String(100), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column("bpm", sa.Integer(), nullable=True),
        sa.Column("musical_key", sa.String(20), nullable=True),
        sa.Column("duration_s", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft", "generating", "review", "approved", "rejected", "failed",
                name="release_status", native_enum=False, length=20,
            ),
            nullable=False,
        ),
        sa.Column("audio_path", sa.String(500), nullable=True),
        sa.Column("audio_url", sa.String(1000), nullable=True),
        sa.Column("workflow_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_releases_status", "releases", ["status"])
    op.create_table(
        "release_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "release_id", sa.Integer(),
            sa.ForeignKey("releases.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_release_events_release_id", "release_events", ["release_id"])


def downgrade() -> None:
    op.drop_index("ix_release_events_release_id", "release_events")
    op.drop_table("release_events")
    op.drop_index("ix_releases_status", "releases")
    op.drop_table("releases")
