"""merge guardian branch heads

Revision ID: revision_merge_guardian_heads
Revises: add_artifact_embedding_org_fk, encrypt_sensitive_columns, revision_guardian_timestamptz
Create Date: 2026-06-01 00:00:01.000000

"""
from typing import Sequence, Union

revision: str = 'revision_merge_guardian_heads'
down_revision: Union[str, tuple] = (
    'add_artifact_embedding_org_fk',
    'encrypt_sensitive_columns',
    'revision_guardian_timestamptz',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
