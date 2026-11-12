"""Add prime_requests (approval inbox + exactly-once execution) and prime_org_limits.

Root cause: Prime could decide but had nowhere to hold a decision that waits for a
person, no record of whether an approved action had been carried out, and its
payment ceiling and longest delegation were constants shared by every organisation.

Revision ID: add_prime_requests_limits
Revises: add_portal_tokens_plan_period
Create Date: 2026-11-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'add_prime_requests_limits'
down_revision: Union[str, None] = 'add_portal_tokens_plan_period'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A database started by create_all (prime/models.py) may already have them.
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "prime_org_limits" not in existing:
        op.create_table(
            "prime_org_limits",
            sa.Column("org_id", sa.String(50), primary_key=True),
            sa.Column("payment_ceiling", sa.String(32), nullable=False),
            sa.Column("max_delegation_days", sa.Integer(), nullable=False),
            sa.Column("updated_by", sa.String(255), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
    if "prime_requests" not in existing:
        op.create_table(
            "prime_requests",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(50), nullable=False),
            sa.Column("action_type", sa.String(64), nullable=False),
            sa.Column("on_behalf_of", sa.String(255), nullable=False),
            sa.Column("requested_by", sa.String(255), nullable=False),
            sa.Column("amount", sa.String(32), nullable=True),
            sa.Column("currency", sa.String(3), nullable=True),
            sa.Column("params", sa.JSON(), nullable=False),
            sa.Column("executor", sa.String(64), nullable=False),
            sa.Column("delegation_id", sa.String(36), nullable=False),
            sa.Column("deputy", sa.String(255), nullable=False),
            sa.Column("outcome", sa.String(32), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("request_hash", sa.String(64), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("decided_by", sa.String(255), nullable=True),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
            sa.Column("decision_reason", sa.Text(), nullable=True),
            sa.Column("decided_hash", sa.String(64), nullable=True),
            sa.Column("exec_status", sa.String(20), nullable=True),
            sa.Column("exec_started_at", sa.DateTime(), nullable=True),
            sa.Column("exec_result", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("request_hash", name="uq_prime_requests_request_hash"),
        )
        for col in ("org_id", "on_behalf_of", "delegation_id", "deputy", "status"):
            op.create_index(f"ix_prime_requests_{col}", "prime_requests", [col])


def downgrade() -> None:
    op.drop_table("prime_requests")
    op.drop_table("prime_org_limits")
