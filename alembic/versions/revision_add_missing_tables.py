"""add missing tables: token_budget_records, llm_cache_entries, installed_plugins,
pipeline_events, notifications

These tables exist in core/models.py but were never added to any migration,
causing fresh production deploys (alembic upgrade head) to miss them silently.

Revision ID: revision_add_missing_tables
Revises: revision_events_timestamp_idx
Create Date: 2026-07-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'revision_add_missing_tables'
down_revision: Union[str, None] = 'revision_events_timestamp_idx'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── llm_cache_entries ─────────────────────────────────────────────────────
    # Shared LLM response cache (replaces per-process SQLite file)
    op.create_table(
        'llm_cache_entries',
        sa.Column('cache_key', sa.String(64), primary_key=True),  # SHA-256 hex
        sa.Column('task_type', sa.String(64), nullable=False),
        sa.Column('response', sa.Text(), nullable=False),
        sa.Column('prompt_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('hit_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.Float(), nullable=False, server_default='0'),
        sa.Column('last_hit_at', sa.Float(), nullable=False, server_default='0'),
    )

    # ── token_budget_records ──────────────────────────────────────────────────
    # Per-org monthly token usage (replaces per-process SQLite file)
    op.create_table(
        'token_budget_records',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('org_id', sa.String(50), nullable=False),
        sa.Column('month', sa.String(7), nullable=False),   # "YYYY-MM"
        sa.Column('input_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('output_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('runs', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cache_hits', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cache_misses', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('estimated_cost_usd', sa.Float(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.Float(), nullable=False, server_default='0'),
    )
    op.create_index('ix_token_budget_records_org_id', 'token_budget_records', ['org_id'])

    # ── installed_plugins ─────────────────────────────────────────────────────
    # Installed plugins per org (replaces per-process SQLite file)
    op.create_table(
        'installed_plugins',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('org_id', sa.String(50), nullable=False),
        sa.Column('plugin_id', sa.String(100), nullable=False),
        sa.Column('config_json', sa.Text(), nullable=True),
        sa.Column('installed_at', sa.Float(), nullable=False, server_default='0'),
        sa.Column('last_tested_at', sa.Float(), nullable=True),
        sa.Column('test_status', sa.String(20), nullable=True),
    )
    op.create_index('ix_installed_plugins_org_id', 'installed_plugins', ['org_id'])

    # ── pipeline_events ───────────────────────────────────────────────────────
    # Persistent record of every pipeline event
    op.create_table(
        'pipeline_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('runs.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_pipeline_events_run_id', 'pipeline_events', ['run_id'])
    op.create_index('ix_pipeline_events_event_type', 'pipeline_events', ['event_type'])
    op.create_index('ix_pipeline_events_created_at', 'pipeline_events', ['created_at'])

    # ── notifications ─────────────────────────────────────────────────────────
    # In-app notifications for org members
    op.create_table(
        'notifications',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('org_id', sa.String(50), nullable=False),
        sa.Column('user_id', sa.String(36), nullable=True),  # None = org-wide
        sa.Column('type', sa.String(64), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('link', sa.String(512), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.Float(), nullable=False, server_default='0'),
    )
    op.create_index('ix_notifications_org_id', 'notifications', ['org_id'])
    op.create_index('ix_notifications_user_id', 'notifications', ['user_id'])


def downgrade() -> None:
    op.drop_table('notifications')
    op.drop_table('pipeline_events')
    op.drop_table('installed_plugins')
    op.drop_table('token_budget_records')
    op.drop_table('llm_cache_entries')
