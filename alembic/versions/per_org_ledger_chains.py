"""Per-organisation audit chains, signed checkpoints, pseudonymous subjects, back-fill marks.

Root cause: every organisation shared one audit chain. All appends serialised on one
lock, one organisation's history could not be verified, exported or erased on its own,
nothing outside the database pinned the chain's tail (a superuser could cut the last
entries unseen), and raw emails/IPs sat in append-only rows with no erasure path.

audit_chain keeps every existing row unchanged: they become the frozen `legacy` chain
(ADD COLUMN ... DEFAULT fills them without an UPDATE, so the append-only trigger is not
involved). New rows carry chain_id + chain_seq; the global seq becomes a sequence.
Inserting into the legacy chain is refused from now on, so its tail (which every new
chain's first entry links to) can no longer move.

Downgrade is refused: it would discard which chain every new entry belongs to.

Revision ID: per_org_ledger_chains
Revises: add_portal_approval_chain
Create Date: 2026-11-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

try:   # one definition shared with the empty-database bootstrap (core/schema_ddl.py)
    from aether_os.core import schema_ddl
except ModuleNotFoundError:   # alembic run from the repository root without PYTHONPATH (alembic.ini prepends ".")
    from core import schema_ddl

revision: str = 'per_org_ledger_chains'
down_revision: Union[str, None] = 'add_portal_approval_chain'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_CHAIN_COLUMNS = """
    ALTER TABLE audit_chain ADD COLUMN chain_id VARCHAR(64) NOT NULL DEFAULT 'legacy';
    ALTER TABLE audit_chain ALTER COLUMN chain_id DROP DEFAULT;
    ALTER TABLE audit_chain ADD COLUMN chain_seq INTEGER;
    ALTER TABLE audit_chain DROP CONSTRAINT audit_chain_prev_hash_key;
    ALTER TABLE audit_chain ADD CONSTRAINT uq_audit_chain_prev UNIQUE (chain_id, prev_hash);
    ALTER TABLE audit_chain ADD CONSTRAINT uq_audit_chain_position UNIQUE (chain_id, chain_seq);
    CREATE INDEX ix_audit_chain_chain_row ON audit_chain (chain_id, seq);
    CREATE SEQUENCE audit_chain_seq_seq OWNED BY audit_chain.seq;
    SELECT setval('audit_chain_seq_seq', COALESCE((SELECT max(seq) FROM audit_chain), 0) + 1, false);
    ALTER TABLE audit_chain ALTER COLUMN seq SET DEFAULT nextval('audit_chain_seq_seq');
"""

def _sqlite_rebuild_audit_chain() -> None:
    # SQLite cannot drop the unnamed UNIQUE(prev_hash); rebuild the table (no triggers there).
    op.execute("ALTER TABLE audit_chain RENAME TO audit_chain_pre_chains")
    op.create_table(
        'audit_chain',
        sa.Column('seq', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('chain_id', sa.String(64), nullable=False),
        sa.Column('chain_seq', sa.Integer(), nullable=True),
        sa.Column('timestamp', sa.Float(), nullable=False),
        sa.Column('actor', sa.String(255), nullable=False),
        sa.Column('action', sa.String(255), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('prev_hash', sa.String(64), nullable=False),
        sa.Column('entry_hash', sa.String(64), nullable=False, unique=True),
        sa.UniqueConstraint('chain_id', 'chain_seq', name='uq_audit_chain_position'),
        sa.UniqueConstraint('chain_id', 'prev_hash', name='uq_audit_chain_prev'),
    )
    op.execute("INSERT INTO audit_chain (seq, chain_id, chain_seq, timestamp, actor, action, payload, "
               "prev_hash, entry_hash) SELECT seq, 'legacy', NULL, timestamp, actor, action, payload, "
               "prev_hash, entry_hash FROM audit_chain_pre_chains")
    op.drop_table('audit_chain_pre_chains')
    op.create_index('ix_audit_chain_chain_row', 'audit_chain', ['chain_id', 'seq'])


def upgrade() -> None:
    bind = op.get_bind()
    pg = bind.dialect.name == 'postgresql'
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    # A database started by create_all already has the new shape.
    if 'chain_id' not in {c['name'] for c in inspector.get_columns('audit_chain')}:
        if pg:
            op.execute(_NEW_CHAIN_COLUMNS)
        else:
            _sqlite_rebuild_audit_chain()

    if 'audit_checkpoints' not in existing:
        op.create_table(
            'audit_checkpoints',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('chain_id', sa.String(64), nullable=False, index=True),
            sa.Column('chain_seq', sa.Integer(), nullable=False),
            sa.Column('head_hash', sa.String(64), nullable=False),
            sa.Column('created_at', sa.Float(), nullable=False),
            sa.Column('key_id', sa.String(32), nullable=False),
            sa.Column('signature', sa.String(128), nullable=False),
            sa.UniqueConstraint('chain_id', 'chain_seq', name='uq_audit_checkpoint_position'),
        )
    if 'audit_org_peppers' not in existing:
        op.create_table(
            'audit_org_peppers',
            sa.Column('chain_id', sa.String(64), primary_key=True),
            sa.Column('pepper', sa.String(64), nullable=False),
            sa.Column('created_at', sa.Float(), nullable=False),
        )
    if 'audit_subjects' not in existing:
        op.create_table(
            'audit_subjects',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('chain_id', sa.String(64), nullable=False, index=True),
            sa.Column('kind', sa.String(16), nullable=False),
            sa.Column('value_hmac', sa.String(64), nullable=False),
            sa.Column('value', sa.Text(), nullable=False),
            sa.Column('created_at', sa.Float(), nullable=False),
            sa.UniqueConstraint('chain_id', 'kind', 'value_hmac', name='uq_audit_subject_value'),
        )
    if 'audit_erasures' not in existing:
        op.create_table(
            'audit_erasures',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('chain_id', sa.String(64), nullable=False, index=True),
            sa.Column('kind', sa.String(16), nullable=True),
            sa.Column('value_hmac', sa.String(64), nullable=True),
            sa.Column('subject_id', sa.String(36), nullable=True),
            sa.Column('erased_at', sa.Float(), nullable=False),
        )
    if 'audit_backfill' not in existing:
        op.create_table(
            'audit_backfill',
            sa.Column('audit_log_id', sa.String(36), primary_key=True),
            sa.Column('entry_hash', sa.String(64), nullable=False),
            sa.Column('imported_at', sa.Float(), nullable=False),
        )
    schema_ddl.apply(bind, only=("audit_chain_legacy_frozen", "audit_checkpoints_no_update_delete"))   # PostgreSQL only


def downgrade() -> None:
    raise NotImplementedError(
        "per_org_ledger_chains cannot be downgraded: it would discard which chain every "
        "audit entry belongs to. Restore from a backup taken before the upgrade instead.")
