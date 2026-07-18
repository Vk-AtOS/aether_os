"""M7: add updated_at column to organisations and users — enables change tracking for core entities

Revision ID: add_updated_at_org_user
Revises: add_saml_config_unique_org_id
Create Date: 2026-07-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_updated_at_org_user'
down_revision: Union[str, None] = 'add_saml_config_unique_org_id'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'organisations',
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True,
                  server_default=sa.func.now()),
    )
    op.add_column(
        'users',
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True,
                  server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_column('users', 'updated_at')
    op.drop_column('organisations', 'updated_at')
