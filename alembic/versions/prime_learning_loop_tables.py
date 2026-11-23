"""learning_uses, learning_item_state, learning_build_outcomes: Prime's one learning loop (KAN-229).

Root cause: three learners (correction memory, golden builds, fix memory) each fed prompts, but nothing recorded
when an item was used or whether it helped, so a lesson that kept making things worse was put into every prompt
forever and nobody could see whether learning improved builds or approvals. These tables record each use and its
outcome, retire items that keep failing, and keep the first-pass build trend. The learners keep their own tables.

Revision ID: prime_learning_loop
Revises: add_prime_consent_learning
Create Date: 2026-11-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'prime_learning_loop'
down_revision: Union[str, None] = 'add_prime_consent_learning'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'learning_uses',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('org_id', sa.String(50), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('item_id', sa.String(64), nullable=False),
        sa.Column('scope', sa.String(200), nullable=False, server_default=''),
        sa.Column('ref', sa.String(64), nullable=True),
        sa.Column('used_at', sa.DateTime(), nullable=False),
        sa.Column('helped', sa.Boolean(), nullable=True),
        sa.Column('settled_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_learning_uses_org_kind_item', 'learning_uses', ['org_id', 'kind', 'item_id'])
    op.create_index('ix_learning_uses_org_used_at', 'learning_uses', ['org_id', 'used_at'])
    op.create_table(
        'learning_item_state',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('org_id', sa.String(50), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('item_id', sa.String(64), nullable=False),
        sa.Column('failures', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('retired', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('retired_at', sa.DateTime(), nullable=True),
        sa.Column('retired_by', sa.String(255), nullable=True),
        sa.Column('retired_reason', sa.String(255), nullable=True),
        sa.UniqueConstraint('org_id', 'kind', 'item_id', name='uq_learning_item_state_item'),
    )
    op.create_index('ix_learning_item_state_org_id', 'learning_item_state', ['org_id'])
    op.create_table(
        'learning_build_outcomes',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('org_id', sa.String(50), nullable=False),
        sa.Column('run_id', sa.String(36), nullable=False, unique=True),
        sa.Column('built', sa.Boolean(), nullable=False),
        sa.Column('first_pass', sa.Boolean(), nullable=False),
        sa.Column('rounds', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_learning_build_outcomes_org_id', 'learning_build_outcomes', ['org_id'])


def downgrade() -> None:
    op.drop_table('learning_build_outcomes')
    op.drop_table('learning_item_state')
    op.drop_table('learning_uses')
