"""add_user_preferences_and_workspaces

Revision ID: revision_d6973beef17f
Revises: revision_474970353032
Create Date: 2026-05-05 20:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'revision_d6973beef17f'
down_revision: Union[str, None] = 'revision_474970353032'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Add user_preferences to users
    op.add_column('users', sa.Column('user_preferences', sa.Text(), nullable=True))
    
    # Create workspaces table
    op.create_table('workspaces',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('preferences', sa.Text(), nullable=False), # JSON
        sa.Column('created_by', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('is_shared', sa.Boolean(), default=False),
    )

def downgrade() -> None:
    op.drop_column('users', 'user_preferences')
    op.drop_table('workspaces')
