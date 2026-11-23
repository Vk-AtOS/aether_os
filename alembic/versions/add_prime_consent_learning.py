"""Prime learning consent and data rights (KAN-228): prime_consents, prime_learned_items, prime_learning_settings.

Root cause: the Prime learning engine (epic KAN-227) is about to learn from people's git, Jira, calendar and
attendance data, and nothing recorded whether a person agreed to that, under which notice, or let them see, export
or erase it (India DPDP Act 2023). Consent is per person and per source, off by default (no row = off); learned
items are per organisation AND person and expire after the organisation's retention period.

Revision ID: add_prime_consent_learning
Revises: fix_memory_tables
Create Date: 2026-11-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'add_prime_consent_learning'
down_revision: Union[str, None] = 'fix_memory_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    have = set(sa.inspect(op.get_bind()).get_table_names())
    if "prime_consents" not in have:
        op.create_table(
            "prime_consents",
            sa.Column("org_id", sa.String(50), primary_key=True),
            sa.Column("user_id", sa.String(255), primary_key=True),
            sa.Column("source", sa.String(16), primary_key=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("enabled_at", sa.DateTime(), nullable=True),
            sa.Column("changed_by", sa.String(255), nullable=False),
            sa.Column("changed_at", sa.DateTime(), nullable=False),
            sa.Column("notice_version", sa.String(32), nullable=False),
            sa.Column("purpose", sa.Text(), nullable=False),
        )
    if "prime_learned_items" not in have:
        op.create_table(
            "prime_learned_items",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(50), nullable=False),
            sa.Column("user_id", sa.String(255), nullable=False),
            sa.Column("source", sa.String(16), nullable=False),
            sa.Column("kind", sa.String(64), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("data", sa.JSON(), nullable=True),
            sa.Column("learned_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_prime_learned_person", "prime_learned_items", ["org_id", "user_id", "source"])
        op.create_index("ix_prime_learned_items_learned_at", "prime_learned_items", ["learned_at"])
    if "prime_learning_settings" not in have:
        op.create_table(
            "prime_learning_settings",
            sa.Column("org_id", sa.String(50), primary_key=True),
            sa.Column("retention_days", sa.Integer(), nullable=False),
            sa.Column("updated_by", sa.String(255), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("prime_learning_settings")
    op.drop_table("prime_learned_items")
    op.drop_table("prime_consents")
