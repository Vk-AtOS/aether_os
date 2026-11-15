"""users.velaris_employee_id: the Velaris employee record a sign-in is (own-record reads)

Revision ID: add_user_velaris_employee_id
Revises: merge_r2_heads
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "add_user_velaris_employee_id"
down_revision: Union[str, None] = "merge_r2_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("velaris_employee_id", sa.String(128), nullable=True))
    # a unique INDEX (SQLite cannot add a constraint to an existing table); NULLs never collide, so unlinked users
    # are unaffected
    op.create_index("uq_users_org_velaris_employee", "users", ["org_id", "velaris_employee_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_users_org_velaris_employee", table_name="users")
    op.drop_column("users", "velaris_employee_id")
