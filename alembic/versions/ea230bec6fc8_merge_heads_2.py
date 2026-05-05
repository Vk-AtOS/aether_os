"""merge_heads_2

Revision ID: ea230bec6fc8
Revises: f3248d2ed62b, revision_1ef04e14f9d0
Create Date: 2026-05-05 06:07:24.319105

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ea230bec6fc8'
down_revision: Union[str, None] = ('f3248d2ed62b', 'revision_1ef04e14f9d0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
