"""multi_tenancy_v1

Revision ID: 4688c33ff6e8
Revises: f9f084df3f49
Create Date: 2026-05-04 00:43:47.094319

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4688c33ff6e8'
down_revision: Union[str, None] = 'f9f084df3f49'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create organisations table
    op.create_table('organisations',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('slug', sa.String(length=255), nullable=False),
        sa.Column('plan', sa.String(length=50), nullable=False, server_default='trial'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('trial_runs_used', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('trial_runs_limit', sa.Integer(), nullable=False, server_default='3'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug')
    )

    # 2. Create users table
    op.create_table('users',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False, server_default='member'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )

    # 3. Create api_keys table
    op.create_table('api_keys',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('org_id', sa.String(length=36), nullable=False),
        sa.Column('key_hash', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('last_used_at', sa.Float(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # 4. Add org_id to runs table
    with op.batch_alter_table('runs') as batch_op:
        batch_op.add_column(sa.Column('org_id', sa.String(length=36), nullable=True))
        batch_op.create_foreign_key('fk_runs_org_id', 'organisations', ['org_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('runs') as batch_op:
        batch_op.drop_constraint('fk_runs_org_id', type_='foreignkey')
        batch_op.drop_column('org_id')
    op.drop_table('api_keys')
    op.drop_table('users')
    op.drop_table('organisations')
