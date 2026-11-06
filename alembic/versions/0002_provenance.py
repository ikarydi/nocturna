"""stage 2: prompt templates, assets with provenance, metadata and checklist

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-06
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags", sa.Text(), nullable=False, server_default=""),
        sa.Column("bpm_min", sa.Integer(), nullable=True),
        sa.Column("bpm_max", sa.Integer(), nullable=True),
        sa.Column("default_key", sa.String(20), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    with op.batch_alter_table("releases") as batch:
        batch.add_column(sa.Column("template_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("seed", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("description", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("credits", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("tags", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("checklist", sa.JSON(), nullable=False, server_default="{}"))
        batch.create_foreign_key(
            "fk_releases_template_id", "prompt_templates", ["template_id"], ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("release_events") as batch:
        batch.add_column(sa.Column("actor", sa.String(100), nullable=False, server_default=""))
    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "release_id", sa.Integer(),
            sa.ForeignKey("releases.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("original_name", sa.String(300), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "parent_id", sa.Integer(),
            sa.ForeignKey("assets.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("codec", sa.String(40), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("channels", sa.Integer(), nullable=True),
        sa.Column("bit_depth", sa.Integer(), nullable=True),
        sa.Column("integrated_lufs", sa.Float(), nullable=True),
        sa.Column("loudness_range_lu", sa.Float(), nullable=True),
        sa.Column("true_peak_dbtp", sa.Float(), nullable=True),
        sa.Column("sample_peak_dbfs", sa.Float(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("qc_warnings", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("provenance", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_assets_release_id", "assets", ["release_id"])


def downgrade() -> None:
    op.drop_index("ix_assets_release_id", "assets")
    op.drop_table("assets")
    with op.batch_alter_table("release_events") as batch:
        batch.drop_column("actor")
    with op.batch_alter_table("releases") as batch:
        batch.drop_constraint("fk_releases_template_id", type_="foreignkey")
        for col in ("checklist", "tags", "credits", "description", "seed", "template_id"):
            batch.drop_column(col)
    op.drop_table("prompt_templates")
