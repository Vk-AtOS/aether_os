"""Add audit_chain (hash-linked, append-only ledger) and prime_delegations.

audit_chain replaces the non-verifiable audit_log.prev_hash scheme: each row
stores prev_hash and its own entry_hash. On PostgreSQL a trigger rejects
UPDATE and DELETE so the table is append-only at the database level too.

Revision ID: add_audit_chain_prime_delegations
Revises: revision_pgvector_artifact_embedding
Create Date: 2026-11-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'add_audit_chain_prime_delegations'
down_revision: Union[str, None] = 'revision_pgvector_artifact_embedding'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'audit_chain',
        sa.Column('seq', sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column('timestamp', sa.Float(), nullable=False),
        sa.Column('actor', sa.String(255), nullable=False),
        sa.Column('action', sa.String(255), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('prev_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('entry_hash', sa.String(64), nullable=False, unique=True),
    )
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("""
            CREATE FUNCTION audit_chain_append_only() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'audit_chain is append-only';
            END;
            $$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER audit_chain_no_update_delete
            BEFORE UPDATE OR DELETE ON audit_chain
            FOR EACH ROW EXECUTE FUNCTION audit_chain_append_only()
        """)

    op.create_table(
        'prime_delegations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('grantor', sa.String(255), nullable=False),
        sa.Column('deputy', sa.String(255), nullable=False),
        sa.Column('scope', sa.JSON(), nullable=False),
        sa.Column('max_amount', sa.String(32), nullable=True),
        sa.Column('currency', sa.String(3), nullable=True),
        sa.Column('autonomy', sa.Integer(), nullable=False),
        sa.Column('valid_from', sa.DateTime(), nullable=False),
        sa.Column('valid_until', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_by', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_prime_delegations_grantor', 'prime_delegations', ['grantor'])


def downgrade() -> None:
    op.drop_index('ix_prime_delegations_grantor', table_name='prime_delegations')
    op.drop_table('prime_delegations')
    op.drop_table('audit_chain')
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("DROP FUNCTION IF EXISTS audit_chain_append_only()")
