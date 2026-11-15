"""add_versioning_storage_webhooks

Revision ID: revision_1ef04e14f9d0
Revises: revision_09ddf4a23dc0
Create Date: 2026-05-05 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'revision_1ef04e14f9d0'
down_revision: Union[str, None] = 'revision_09ddf4a23dc0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Add run_version to runs
    op.add_column('runs', sa.Column('run_version', sa.Integer(), nullable=False, server_default='1'))
    
    # Add storage_used_mb to organisations
    op.add_column('organisations', sa.Column('storage_used_mb', sa.Float(), nullable=False, server_default='0.0'))
    
    # Create webhooks table
    op.create_table('webhooks',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('events', sa.Text(), nullable=False), # JSON
        sa.Column('secret', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('last_triggered_at', sa.Float(), nullable=True),
    )

def downgrade() -> None:
    op.drop_column('runs', 'run_version')
    op.drop_column('organisations', 'storage_used_mb')
    op.drop_table('webhooks')
