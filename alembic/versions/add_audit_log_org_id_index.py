"""M4: add index on audit_log.org_id — eliminates full table scan on every compliance query

Revision ID: add_audit_log_org_id_index
Revises: add_webhook_secret_hash
Create Date: 2026-07-18

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'add_audit_log_org_id_index'
down_revision: Union[str, None] = 'add_webhook_secret_hash'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_audit_logs_org_id', 'audit_log', ['org_id'])


def downgrade() -> None:
    op.drop_index('ix_audit_logs_org_id', table_name='audit_log')
