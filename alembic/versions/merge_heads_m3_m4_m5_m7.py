"""merge all current heads before adding M3/M4/M5/M7 columns

Revision ID: merge_heads_m3_m4_m5_m7
Revises: add_questionnaire_sessions, add_scim_token_hash,
         revision_add_missing_tables, revision_add_org_api_keys
Create Date: 2026-07-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'merge_heads_m3_m4_m5_m7'
down_revision: Union[str, None] = (
    'add_questionnaire_sessions',
    'add_scim_token_hash',
    'revision_add_missing_tables',
    'revision_add_org_api_keys',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
