"""add_council_columns_and_llm_config_table

Revision ID: revision_e1f2a3b4c5d6
Revises: 3815540c9443
Create Date: 2026-05-14 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'revision_e1f2a3b4c5d6'
down_revision: Union[str, None] = '3815540c9443'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Council review result columns on runs table
    op.add_column('runs', sa.Column('council_preflight', sa.JSON(), nullable=True))
    op.add_column('runs', sa.Column('council_delivery',  sa.JSON(), nullable=True))

    # llm_config: per-org (or global) LLM provider configuration.
    # NOTE (DB-001): This table is intentionally unused at runtime.  The active
    # LLM configuration is sourced from environment variables (os.environ) via
    # core/llm/client.py.  The table is created here to keep the migration chain
    # intact and allow future DB-backed per-org config without a new migration.
    op.create_table(
        'llm_config',
        sa.Column('id',                  sa.String(36),   primary_key=True),
        sa.Column('org_id',              sa.String(36),   nullable=True,  index=True),
        sa.Column('provider',            sa.String(64),   nullable=False, default='openrouter'),
        sa.Column('heavy_model',         sa.String(256),  nullable=True),
        sa.Column('light_model',         sa.String(256),  nullable=True),
        sa.Column('prefer_paid',         sa.Boolean(),    nullable=False, default=False),
        sa.Column('council_enabled',     sa.Boolean(),    nullable=False, default=True),
        sa.Column('council_strict_mode', sa.Boolean(),    nullable=False, default=False),
        sa.Column('updated_at',          sa.Float(),      nullable=True),
    )


def downgrade() -> None:
    op.drop_table('llm_config')
    op.drop_column('runs', 'council_delivery')
    op.drop_column('runs', 'council_preflight')
