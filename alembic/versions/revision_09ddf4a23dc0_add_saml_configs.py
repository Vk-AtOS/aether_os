"""add_saml_configs

Revision ID: revision_09ddf4a23dc0
Revises: f9f084df3f49
Create Date: 2026-05-05 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import uuid

revision: str = 'revision_09ddf4a23dc0'
down_revision: Union[str, None] = 'f9f084df3f49'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table('saml_configs',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('idp_entity_id', sa.Text(), nullable=False),
        sa.Column('idp_sso_url', sa.Text(), nullable=False),
        sa.Column('idp_cert', sa.Text(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
    )

def downgrade() -> None:
    op.drop_table('saml_configs')
