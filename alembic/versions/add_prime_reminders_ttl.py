"""Add prime_requests.reminded_at / expiry_notified_at and prime_org_limits.request_ttl_hours (KAN-26).

Root cause: the 72h approval lifetime was a constant for every organisation, and nothing told
an approver a request was about to lapse or told the requester it had: an expired request just
stopped appearing. The two nullable columns are the once-only claims of the reminder sweep.

Revision ID: add_prime_reminders_ttl
Revises: add_prime_request_revisions
Create Date: 2026-11-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'add_prime_reminders_ttl'
down_revision: Union[str, None] = 'add_prime_request_revisions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    req = {c["name"] for c in insp.get_columns("prime_requests")}
    for name in ("reminded_at", "expiry_notified_at"):
        if name not in req:
            op.add_column("prime_requests", sa.Column(name, sa.DateTime(), nullable=True))
    if "request_ttl_hours" not in {c["name"] for c in insp.get_columns("prime_org_limits")}:
        op.add_column("prime_org_limits", sa.Column("request_ttl_hours", sa.Integer(), nullable=False,
                                                    server_default=sa.text("72")))
    # The sweep and the queue filter on (status, expires_at).
    if "ix_prime_requests_status_expires" not in {i["name"] for i in insp.get_indexes("prime_requests")}:
        op.create_index("ix_prime_requests_status_expires", "prime_requests", ["status", "expires_at"])


def downgrade() -> None:
    op.drop_index("ix_prime_requests_status_expires", table_name="prime_requests")
    op.drop_column("prime_org_limits", "request_ttl_hours")
    op.drop_column("prime_requests", "expiry_notified_at")
    op.drop_column("prime_requests", "reminded_at")
