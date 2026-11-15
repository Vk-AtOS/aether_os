"""merge_heads

Revision ID: f3248d2ed62b
Revises: 4688c33ff6e8, revision_09ddf4a23dc0
Create Date: 2026-05-05 05:51:55.651131

"""
from typing import Sequence, Union



# revision identifiers, used by Alembic.
revision: str = 'f3248d2ed62b'
down_revision: Union[str, None] = ('4688c33ff6e8', 'revision_09ddf4a23dc0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
