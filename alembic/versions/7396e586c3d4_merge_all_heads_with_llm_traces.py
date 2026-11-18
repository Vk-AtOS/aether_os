"""merge_all_heads_with_llm_traces

Revision ID: 7396e586c3d4
Revises: a1b2c3d4e5f6, add_learning_clarifications, encrypt_sensitive_columns
Create Date: 2026-06-07 19:30:53.533974

"""
from typing import Sequence, Union



# revision identifiers, used by Alembic.
revision: str = '7396e586c3d4'
down_revision: Union[str, None] = ('a1b2c3d4e5f6', 'add_learning_clarifications', 'encrypt_sensitive_columns')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
