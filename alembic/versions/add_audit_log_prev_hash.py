"""add prev_hash to audit_log for hash-chaining (SOC 2 tamper evidence)

Revision ID: add_audit_log_prev_hash
Revises: add_codebase_profiles
Create Date: 2026-06-04
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_audit_log_prev_hash'
down_revision = 'add_codebase_profiles'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'audit_log',
        sa.Column('prev_hash', sa.String(64), nullable=True),
    )


def downgrade():
    op.drop_column('audit_log', 'prev_hash')
