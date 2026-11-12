"""Add portal_tokens, portal_approvals and organisations.plan_period_end.

Root causes:
  * Nothing could issue a client-portal token (the only "token" was a plaintext
    file beside the project that no endpoint created), and POST /portal/{id}/approve
    had nowhere to record an approval. portal_tokens holds only a SHA-256 of each
    token, with expiry and revocation; portal_approvals holds the client's decisions.
  * A paid plan never ended: billing_payments stops replay but nothing recorded
    how long a payment buys. plan_period_end (unix seconds) is that record.

Revision ID: add_portal_tokens_plan_period
Revises: add_billing_payments
Create Date: 2026-11-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'add_portal_tokens_plan_period'
down_revision: Union[str, None] = 'add_billing_payments'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A database started by create_all already has whatever the models declared at the time.
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())

    if "plan_period_end" not in {c["name"] for c in insp.get_columns("organisations")}:
        op.add_column("organisations", sa.Column("plan_period_end", sa.Float(), nullable=True))

    if "portal_tokens" not in tables:
        op.create_table(
            "portal_tokens",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(50), nullable=False),
            sa.Column("project_id", sa.String(128), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("label", sa.String(120), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(64), nullable=False),
            sa.Column("created_at", sa.Float(), nullable=False),
            sa.Column("expires_at", sa.Float(), nullable=False),
            sa.Column("revoked_at", sa.Float(), nullable=True),
            sa.Column("revoked_by", sa.String(64), nullable=True),
            sa.Column("last_used_at", sa.Float(), nullable=True),
        )
        op.create_index("ix_portal_tokens_org_id", "portal_tokens", ["org_id"])
        op.create_index("ix_portal_tokens_project_id", "portal_tokens", ["project_id"])

    if "portal_approvals" not in tables:
        op.create_table(
            "portal_approvals",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("org_id", sa.String(50), nullable=False),
            sa.Column("project_id", sa.String(128), nullable=False),
            sa.Column("approved", sa.Boolean(), nullable=False),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("actor_kind", sa.String(20), nullable=False),
            sa.Column("actor_id", sa.String(64), nullable=False),
            sa.Column("actor_label", sa.String(255), nullable=False, server_default=""),
            sa.Column("applied_to", sa.String(40), nullable=True),
            sa.Column("created_at", sa.Float(), nullable=False),
        )
        op.create_index("ix_portal_approvals_org_id", "portal_approvals", ["org_id"])
        op.create_index("ix_portal_approvals_project_id", "portal_approvals", ["project_id"])


def downgrade() -> None:
    op.drop_table("portal_approvals")
    op.drop_table("portal_tokens")
    op.drop_column("organisations", "plan_period_end")
