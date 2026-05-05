"""merge_heads_3

Revision ID: ffd126a9bb7f
Revises: revision_85f8b596aaf5, revision_a6ed6297ffcf
Create Date: 2026-05-05 07:03:57.319768

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ffd126a9bb7f'
down_revision: Union[str, None] = ('revision_85f8b596aaf5', 'revision_a6ed6297ffcf')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
