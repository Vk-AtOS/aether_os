"""API key scopes (KAN-187)

Root cause: an API key could do everything its organisation's "api" role can do; a CI job that only
reads got the same power as one that deploys. Existing keys keep read+write (so nothing breaks);
new keys can be limited to read.

Revision ID: add_api_key_scopes
Revises: add_org_id_to_run_tables
Create Date: 2026-11-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'add_api_key_scopes'
down_revision: Union[str, None] = 'add_org_id_to_run_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("api_keys")}
    if "scopes" not in cols:
        op.add_column("api_keys", sa.Column("scopes", sa.String(100), nullable=False, server_default="read,write"))


def downgrade() -> None:
    op.drop_column("api_keys", "scopes")
