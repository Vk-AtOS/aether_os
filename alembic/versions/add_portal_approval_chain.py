"""Make client-portal approvals race-safe: portal_approvals.prev_approval_id + unique chain.

Root cause: record_approval read the actor's latest decision and then inserted, so
two identical requests arriving together both saw "no such decision yet" and both
inserted (and both were ledgered). Each row now names the decision it follows,
and (project_id, actor_kind, actor_id, prev_approval_id) is unique, so only one of
two concurrent requests can append; the other re-reads and returns that row.

Existing rows get "legacy:<id>" so they never collide with each other or with a
new row (new rows name a real row id, or "" for an actor's first decision).

Revision ID: add_portal_approval_chain
Revises: add_prime_requests_limits
Create Date: 2026-11-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'add_portal_approval_chain'
down_revision: Union[str, None] = 'add_prime_requests_limits'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UQ = "uq_portal_approvals_actor_chain"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    columns = {c["name"] for c in insp.get_columns("portal_approvals")}
    if "prev_approval_id" not in columns:
        op.add_column("portal_approvals", sa.Column(
            "prev_approval_id", sa.String(48), nullable=False, server_default=""))
        op.execute("UPDATE portal_approvals SET prev_approval_id = 'legacy:' || id")
    if _UQ not in {u["name"] for u in insp.get_unique_constraints("portal_approvals")}:
        with op.batch_alter_table("portal_approvals") as batch:
            batch.create_unique_constraint(
                _UQ, ["project_id", "actor_kind", "actor_id", "prev_approval_id"])


def downgrade() -> None:
    with op.batch_alter_table("portal_approvals") as batch:
        batch.drop_constraint(_UQ, type_="unique")
        batch.drop_column("prev_approval_id")
