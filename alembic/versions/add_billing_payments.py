"""Add billing_payments: one row per provider order/payment that changed a plan.

Root cause: POST /billing/verify-payment (and the Razorpay webhook) set the org's
plan from a paid order without remembering the order, so the same paid order
could be presented again, for example after a cancel, and upgrade the org again.
The unique constraints let the database refuse a second application, including
one racing the first.

Revision ID: add_billing_payments
Revises: fix_schema_drift_guardian_webhooks
Create Date: 2026-11-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'add_billing_payments'
down_revision: Union[str, None] = 'fix_schema_drift_guardian_webhooks'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A database started by create_all (core.billing.payments.BillingPayment) already has it.
    if "billing_payments" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "billing_payments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("order_id", sa.String(100), nullable=False),
        sa.Column("payment_id", sa.String(100), nullable=False),
        sa.Column("org_id", sa.String(50), nullable=False),
        sa.Column("plan", sa.String(50), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.UniqueConstraint("provider", "order_id", name="uq_billing_payments_order"),
        sa.UniqueConstraint("provider", "payment_id", name="uq_billing_payments_payment"),
    )
    op.create_index("ix_billing_payments_org_id", "billing_payments", ["org_id"])


def downgrade() -> None:
    op.drop_table("billing_payments")
