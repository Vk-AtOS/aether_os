"""add stripe_customer_id to organisations

Revision ID: add_stripe_customer_id
Revises: add_audit_log_prev_hash
Create Date: 2026-06-04
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_stripe_customer_id'
down_revision = 'add_audit_log_prev_hash'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'organisations',
        sa.Column('stripe_customer_id', sa.String(64), nullable=True),
    )


def downgrade():
    op.drop_column('organisations', 'stripe_customer_id')
