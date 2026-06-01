"""guardian datetime columns: TIMESTAMP → TIMESTAMPTZ

Revision ID: revision_guardian_timestamptz
Revises: revision_guardian_module
Create Date: 2026-06-01 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op

revision: str = 'revision_guardian_timestamptz'
down_revision: Union[str, None] = 'revision_guardian_module'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE guardian_events "
        "ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC', "
        "ALTER COLUMN resolved_at TYPE TIMESTAMPTZ USING resolved_at AT TIME ZONE 'UTC'"
    )
    op.execute(
        "ALTER TABLE guardian_snapshots "
        "ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE guardian_events "
        "ALTER COLUMN created_at TYPE TIMESTAMP WITHOUT TIME ZONE USING created_at AT TIME ZONE 'UTC', "
        "ALTER COLUMN resolved_at TYPE TIMESTAMP WITHOUT TIME ZONE USING resolved_at AT TIME ZONE 'UTC'"
    )
    op.execute(
        "ALTER TABLE guardian_snapshots "
        "ALTER COLUMN created_at TYPE TIMESTAMP WITHOUT TIME ZONE USING created_at AT TIME ZONE 'UTC'"
    )
