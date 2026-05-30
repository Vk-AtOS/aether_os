"""add org_id FK to artifact_embeddings

Revision ID: add_artifact_embedding_org_fk
Revises: revision_guardian_module
Create Date: 2026-05-30
"""
from alembic import op

revision = 'add_artifact_embedding_org_fk'
down_revision = 'revision_guardian_module'
branch_labels = None
depends_on = None


def upgrade():
    # Ensure organisations.id has a PK before adding the FK reference.
    # On older deployments the column was NOT NULL but lacked the constraint.
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name='organisations' AND constraint_type='PRIMARY KEY'
            ) THEN
                ALTER TABLE organisations ADD PRIMARY KEY (id);
            END IF;
        END $$;
    """)
    op.create_foreign_key(
        'fk_artifact_embeddings_org_id',
        'artifact_embeddings', 'organisations',
        ['org_id'], ['id'],
        ondelete='CASCADE'
    )


def downgrade():
    op.drop_constraint('fk_artifact_embeddings_org_id', 'artifact_embeddings', type_='foreignkey')
