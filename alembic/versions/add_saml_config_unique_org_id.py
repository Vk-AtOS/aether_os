"""M5: add unique constraint on saml_configs.org_id — prevents multiple SAML configs per org

Revision ID: add_saml_config_unique_org_id
Revises: add_audit_log_org_id_index
Create Date: 2026-07-18

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'add_saml_config_unique_org_id'
down_revision: Union[str, None] = 'add_audit_log_org_id_index'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint('uq_saml_config_org_id', 'saml_configs', ['org_id'])


def downgrade() -> None:
    op.drop_constraint('uq_saml_config_org_id', 'saml_configs', type_='unique')
