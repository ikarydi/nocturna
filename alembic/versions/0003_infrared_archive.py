"""infrared archive: capture time, YouTube uploads, starter lane templates

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-18
"""
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# Starter lanes approved for the first YouTube test (3 genres + 5 fusions). Editable later.
LANES = [
    ("Afro house - after hours", "Lead lane: 1 hour after-hours mixes",
     "afro house, organic house, hand percussion, shakers, warm sub bass, hypnotic groove, "
     "deep night atmosphere, instrumental", 118, 124, "A minor"),
    ("Dark ambient - sleep and focus", "Base lane: long-form sleep and focus",
     "dark ambient, slow drones, long reverb, soft textures, no drums, calm, instrumental",
     50, 70, "D minor"),
    ("Speed garage - Shorts", "Test lane: 30 to 45 second Shorts",
     "speed garage, 2-step shuffle, rolling bass, chopped organ stabs, energetic drop, "
     "instrumental", 130, 136, "F minor"),
    ("Infrared house", "Fusion: Afro house x dark ambient, the signature lane",
     "afro house, dark ambient drones, organic percussion, field recording textures, deep sub "
     "bass, slow build, instrumental", 118, 122, "C# minor"),
    ("Ambient jungle", "Fusion: jungle breaks under dark ambient pads",
     "atmospheric jungle, soft breakbeats, half-time pads, deep reese bass, rain textures, "
     "instrumental", 160, 170, "E minor"),
    ("Cinematic amapiano", "Fusion: log drums with cinematic strings and piano",
     "amapiano, log drum bass, cinematic strings, slow piano chords, airy pads, instrumental",
     110, 115, "G minor"),
    ("Cathedral techno", "Fusion: hard techno with organ drones; breakdown and drop for Shorts",
     "hard techno, distorted kick, organ drones, cavernous reverb, long breakdown, big drop, "
     "instrumental", 140, 150, "B minor"),
    ("Folk-electronic", "Fusion: Central European folk instruments over a house groove",
     "deep house groove, cimbalom motif, folk violin phrases, warm bass, organic percussion, "
     "instrumental", 118, 124, "D minor"),
]


def upgrade() -> None:
    with op.batch_alter_table("releases") as batch:
        batch.add_column(sa.Column("capture_time", sa.String(5), nullable=True))
    op.create_table(
        "youtube_uploads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "release_id", sa.Integer(),
            sa.ForeignKey("releases.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("publish_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("video_id", sa.String(40), nullable=True),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(100), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_youtube_uploads_release_id", "youtube_uploads", ["release_id"])

    templates = sa.table(
        "prompt_templates",
        sa.column("name", sa.String), sa.column("description", sa.Text),
        sa.column("tags", sa.Text), sa.column("bpm_min", sa.Integer),
        sa.column("bpm_max", sa.Integer), sa.column("default_key", sa.String),
        sa.column("active", sa.Boolean), sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    existing = {row[0] for row in op.get_bind().execute(sa.text("SELECT name FROM prompt_templates"))}
    now = datetime.now(UTC)
    rows = [
        {"name": n, "description": d, "tags": t, "bpm_min": lo, "bpm_max": hi,
         "default_key": k, "active": True, "created_at": now, "updated_at": now}
        for n, d, t, lo, hi, k in LANES if n not in existing
    ]
    if rows:
        op.bulk_insert(templates, rows)


def downgrade() -> None:
    op.drop_index("ix_youtube_uploads_release_id", "youtube_uploads")
    op.drop_table("youtube_uploads")
    with op.batch_alter_table("releases") as batch:
        batch.drop_column("capture_time")
