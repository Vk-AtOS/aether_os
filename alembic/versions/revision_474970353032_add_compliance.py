"""add_compliance_rbac_sovereignty

Revision ID: revision_474970353032
Revises: revision_4d5c94389944
Create Date: 2026-05-05 18:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'revision_474970353032'
down_revision: Union[str, None] = 'revision_4d5c94389944'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column('organisations', sa.Column('data_region', sa.String(length=20), server_default='global', nullable=False))

def downgrade() -> None:
    op.drop_column('organisations', 'data_region')
