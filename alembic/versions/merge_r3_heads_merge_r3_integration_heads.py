"""merge r3 integration heads

Revision ID: merge_r3_heads
Revises: add_password_history, add_user_velaris_employee_id
Create Date: 2026-11-17 20:37:00.208435

"""
from typing import Sequence, Union



# revision identifiers, used by Alembic.
revision: str = 'merge_r3_heads'
down_revision: Union[str, None] = ('add_password_history', 'add_user_velaris_employee_id')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
