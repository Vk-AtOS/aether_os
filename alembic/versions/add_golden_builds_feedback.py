"""add build_feedback and golden_builds tables

Revision ID: add_golden_builds_feedback
Revises: add_pipeline_run_checkpoint
Create Date: 2026-06-05
"""
from alembic import op
import sqlalchemy as sa

revision = "add_golden_builds_feedback"
down_revision = "add_pipeline_run_checkpoint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "build_feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("org_id", sa.String(36), nullable=False, index=True),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "golden_builds",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False, index=True),
        sa.Column("org_id", sa.String(36), nullable=False, index=True),
        sa.Column("domain", sa.String(50), nullable=False, index=True),
        sa.Column("project_name", sa.String(255), nullable=False),
        sa.Column("prompt_summary", sa.Text(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("user_rating", sa.Float(), nullable=True),
        sa.Column("p04_sample", sa.Text(), nullable=True),
        sa.Column("p05_sample", sa.Text(), nullable=True),
        sa.Column("entity_count", sa.Integer(), nullable=True),
        sa.Column("domain_ir_summary", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("golden_builds")
    op.drop_table("build_feedback")
