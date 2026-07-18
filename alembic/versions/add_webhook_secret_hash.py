"""M3: add webhook secret_hash column; deprecate plaintext secret column

Stores bcrypt hash of webhook secret instead of plaintext.
The raw secret is returned once at creation time and never persisted.

Revision ID: add_webhook_secret_hash
Revises: merge_heads_m3_m4_m5_m7
Create Date: 2026-07-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_webhook_secret_hash'
down_revision: Union[str, None] = 'merge_heads_m3_m4_m5_m7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add secret_hash column for bcrypt-hashed secrets (M3)
    op.add_column('webhooks', sa.Column('secret_hash', sa.String(255), nullable=True))
    # Make the plaintext secret column nullable (deprecated — will be cleared over time)
    op.alter_column('webhooks', 'secret', nullable=True)


def downgrade() -> None:
    op.drop_column('webhooks', 'secret_hash')
    op.alter_column('webhooks', 'secret', nullable=False)
