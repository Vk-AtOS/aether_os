"""merge_heads

Revision ID: 08426bb9c4b3
Revises: 7396e586c3d4, revision_events_timestamp_idx
Create Date: 2026-06-11 00:33:57.279250

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '08426bb9c4b3'
down_revision: Union[str, None] = ('7396e586c3d4', 'revision_events_timestamp_idx')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
