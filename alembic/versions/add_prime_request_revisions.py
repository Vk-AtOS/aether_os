"""Add prime_requests.revision and edited_by (edit-before-approve, KAN-22).

Root cause: a request could not change once submitted, so a wrong amount meant reject and
resubmit, losing the audit trail between the two. An edit now makes a new revision with a
new request hash; edited_by lists everyone who changed it (they may never decide it).

Revision ID: add_prime_request_revisions
Revises: merge_a4_a7_heads
Create Date: 2026-11-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'add_prime_request_revisions'
down_revision: Union[str, None] = 'merge_a4_a7_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("prime_requests")}
    if "revision" not in cols:
        op.add_column("prime_requests",
                      sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("0")))
    if "edited_by" not in cols:
        op.add_column("prime_requests", sa.Column("edited_by", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("prime_requests", "edited_by")
    op.drop_column("prime_requests", "revision")
