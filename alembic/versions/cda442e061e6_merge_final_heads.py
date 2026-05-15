"""merge_final_heads

Revision ID: cda442e061e6
Revises: revision_b1c2d3e4f5a6, revision_e1f2a3b4c5d6
Create Date: 2026-05-15 16:06:33.556685

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cda442e061e6'
down_revision: Union[str, None] = ('revision_b1c2d3e4f5a6', 'revision_e1f2a3b4c5d6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
