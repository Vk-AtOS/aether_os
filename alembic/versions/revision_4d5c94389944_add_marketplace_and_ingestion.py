"""add_marketplace_and_code_ingestion

Revision ID: revision_4d5c94389944
Revises: ffd126a9bb7f
Create Date: 2026-05-05 16:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'revision_4d5c94389944'
down_revision: Union[str, None] = 'ffd126a9bb7f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table('marketplace_profiles',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('base_domain', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('price_usd', sa.Float(), nullable=False),
        sa.Column('profile_yaml', sa.Text(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
    )
    op.create_table('org_code_profiles',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('preferred_language', sa.String(length=50), nullable=True),
        sa.Column('preferred_framework', sa.String(length=50), nullable=True),
        sa.Column('naming_convention', sa.String(length=50), nullable=True),
        sa.Column('test_framework', sa.String(length=50), nullable=True),
        sa.Column('patterns_detected', sa.Text(), nullable=True), # JSON
        sa.Column('custom_patterns', sa.Text(), nullable=True), # JSON
        sa.Column('updated_at', sa.Float(), nullable=False),
    )

def downgrade() -> None:
    op.drop_table('marketplace_profiles')
    op.drop_table('org_code_profiles')
