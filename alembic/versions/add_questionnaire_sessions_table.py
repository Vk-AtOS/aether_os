"""add questionnaire_sessions table

Revision ID: add_questionnaire_sessions
Revises: 2b2463983a2a
Create Date: 2026-07-03 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'add_questionnaire_sessions'
down_revision: Union[str, None] = '2b2463983a2a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'questionnaire_sessions',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('run_id', sa.String(length=36), sa.ForeignKey('runs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('stage_id', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('access_token', sa.String(length=64), nullable=False, unique=True, index=True),
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('respondent_email', sa.String(length=255), nullable=True),
        sa.Column('respondent_name', sa.String(length=255), nullable=True),
        sa.Column('agency_name', sa.String(length=255), nullable=True),
        sa.Column('agency_logo_url', sa.String(length=512), nullable=True),
        sa.Column('questions', sa.JSON(), nullable=False),
        sa.Column('answers', sa.JSON(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )


def downgrade() -> None:
    op.drop_table('questionnaire_sessions')
