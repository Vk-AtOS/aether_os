"""Add prime_corrections (correction memory, KAN-24).

Root cause: an approver's edit or rejection reason was thrown away after the decision, so the
agent that proposed the action made the same mistake next time. Each correction is stored once
(unique ref), per organisation, with personal data pseudonymised.

Revision ID: add_prime_corrections
Revises: add_prime_reminders_ttl
Create Date: 2026-11-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'add_prime_corrections'
down_revision: Union[str, None] = 'add_prime_reminders_ttl'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "prime_corrections" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "prime_corrections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(50), nullable=False),
        sa.Column("agent", sa.String(128), nullable=False),
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("ref", sa.String(80), nullable=False),
        sa.Column("input_summary", sa.Text(), nullable=False),
        sa.Column("proposed", sa.Text(), nullable=False),
        sa.Column("corrected", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("approver_role", sa.String(32), nullable=True),
        sa.Column("on_behalf_of", sa.String(255), nullable=False),
        sa.Column("requested_by", sa.String(255), nullable=False),
        sa.Column("corrected_by", sa.String(255), nullable=False),
        sa.Column("good_example", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("changed_outcome_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("ref", name="uq_prime_corrections_ref"),
    )
    op.create_index("ix_prime_corrections_org_id", "prime_corrections", ["org_id"])
    op.create_index("ix_prime_corrections_on_behalf_of", "prime_corrections", ["on_behalf_of"])
    op.create_index("ix_prime_corrections_lookup", "prime_corrections", ["org_id", "agent", "action_type"])


def downgrade() -> None:
    op.drop_table("prime_corrections")
