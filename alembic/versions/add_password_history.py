"""password history table (KAN-187)

Root cause: nothing remembered old passwords, so a forced rotation could be answered by typing the
same password again. Hashes of the previous passwords are kept (AETHER_PASSWORD_HISTORY, default 5).

Revision ID: add_password_history
Revises: add_api_key_scopes
Create Date: 2026-11-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'add_password_history'
down_revision: Union[str, None] = 'add_api_key_scopes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "password_history" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "password_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_password_history_user_created", "password_history", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_password_history_user_created", table_name="password_history")
    op.drop_table("password_history")
