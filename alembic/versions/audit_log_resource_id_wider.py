"""audit_log.resource_id: String(36) -> String(255).

Root cause: resource ids are not always UUIDs (organisation ids are String(50), others are
paths or composite keys); PostgreSQL rejects the longer value and the audit row is lost.

Revision ID: audit_log_resource_id_wider
Revises: token_budget_unique_org_month
Create Date: 2026-11-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'audit_log_resource_id_wider'
down_revision: Union[str, None] = 'token_budget_unique_org_month'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("audit_log") as batch:
        batch.alter_column("resource_id", existing_type=sa.String(36), type_=sa.String(255), existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("audit_log") as batch:
        batch.alter_column("resource_id", existing_type=sa.String(255), type_=sa.String(36), existing_nullable=False)
