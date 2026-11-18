"""prefix_org_ids

Revision ID: 2559620361b4
Revises: 3a646dd3b217
Create Date: 2026-06-11 00:47:32.530165

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '2559620361b4'
down_revision: Union[str, None] = '3a646dd3b217'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop foreign keys
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_org_id_fkey")
    op.execute("ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS api_keys_org_id_fkey")
    op.execute("ALTER TABLE runs DROP CONSTRAINT IF EXISTS runs_org_id_fkey")
    op.execute("ALTER TABLE user_learning_patterns DROP CONSTRAINT IF EXISTS user_learning_patterns_org_id_fkey")
    op.execute("ALTER TABLE codebase_profiles DROP CONSTRAINT IF EXISTS codebase_profiles_org_id_fkey")

    # 2. Increase column lengths
    op.execute("ALTER TABLE organisations ALTER COLUMN id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE users ALTER COLUMN org_id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE api_keys ALTER COLUMN org_id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE runs ALTER COLUMN org_id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE phase_configs ALTER COLUMN org_id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE decisions ALTER COLUMN org_id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE webhooks ALTER COLUMN org_id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE workspaces ALTER COLUMN org_id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE org_api_keys ALTER COLUMN org_id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE audit_log ALTER COLUMN org_id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE saml_configs ALTER COLUMN org_id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE artifact_embeddings ALTER COLUMN org_id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE marketplace_profiles ALTER COLUMN org_id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE token_budget_records ALTER COLUMN org_id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE llm_call_records ALTER COLUMN org_id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE installed_plugins ALTER COLUMN org_id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE llm_config ALTER COLUMN org_id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE user_learning_patterns ALTER COLUMN org_id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE learning_clarifications_pending ALTER COLUMN org_id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE notifications ALTER COLUMN org_id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE codebase_profiles ALTER COLUMN org_id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE build_feedback ALTER COLUMN org_id TYPE VARCHAR(50)")
    op.execute("ALTER TABLE golden_builds ALTER COLUMN org_id TYPE VARCHAR(50)")

    # 3. Data migration
    op.execute("UPDATE organisations SET id = 'org_' || id WHERE id NOT LIKE 'org_%'")
    op.execute("UPDATE users SET org_id = 'org_' || org_id WHERE org_id NOT LIKE 'org_%'")
    op.execute("UPDATE api_keys SET org_id = 'org_' || org_id WHERE org_id NOT LIKE 'org_%'")
    op.execute("UPDATE runs SET org_id = 'org_' || org_id WHERE org_id NOT LIKE 'org_%'")
    op.execute("UPDATE phase_configs SET org_id = 'org_' || org_id WHERE org_id NOT LIKE 'org_%'")
    op.execute("UPDATE decisions SET org_id = 'org_' || org_id WHERE org_id NOT LIKE 'org_%'")
    op.execute("UPDATE webhooks SET org_id = 'org_' || org_id WHERE org_id NOT LIKE 'org_%'")
    op.execute("UPDATE workspaces SET org_id = 'org_' || org_id WHERE org_id NOT LIKE 'org_%'")
    op.execute("UPDATE org_api_keys SET org_id = 'org_' || org_id WHERE org_id NOT LIKE 'org_%'")
    op.execute("UPDATE audit_log SET org_id = 'org_' || org_id WHERE org_id NOT LIKE 'org_%'")
    op.execute("UPDATE saml_configs SET org_id = 'org_' || org_id WHERE org_id NOT LIKE 'org_%'")
    op.execute("UPDATE artifact_embeddings SET org_id = 'org_' || org_id WHERE org_id NOT LIKE 'org_%'")
    op.execute("UPDATE marketplace_profiles SET org_id = 'org_' || org_id WHERE org_id NOT LIKE 'org_%'")
    op.execute("UPDATE token_budget_records SET org_id = 'org_' || org_id WHERE org_id NOT LIKE 'org_%'")
    op.execute("UPDATE llm_call_records SET org_id = 'org_' || org_id WHERE org_id NOT LIKE 'org_%'")
    op.execute("UPDATE installed_plugins SET org_id = 'org_' || org_id WHERE org_id NOT LIKE 'org_%'")
    op.execute("UPDATE llm_config SET org_id = 'org_' || org_id WHERE org_id NOT LIKE 'org_%'")
    op.execute("UPDATE user_learning_patterns SET org_id = 'org_' || org_id WHERE org_id NOT LIKE 'org_%'")
    op.execute("UPDATE learning_clarifications_pending SET org_id = 'org_' || org_id WHERE org_id NOT LIKE 'org_%'")
    op.execute("UPDATE notifications SET org_id = 'org_' || org_id WHERE org_id NOT LIKE 'org_%'")
    op.execute("UPDATE codebase_profiles SET org_id = 'org_' || org_id WHERE org_id NOT LIKE 'org_%'")
    op.execute("UPDATE build_feedback SET org_id = 'org_' || org_id WHERE org_id NOT LIKE 'org_%'")
    op.execute("UPDATE golden_builds SET org_id = 'org_' || org_id WHERE org_id NOT LIKE 'org_%'")

    # 4. Recreate foreign keys
    op.execute("ALTER TABLE users ADD CONSTRAINT users_org_id_fkey FOREIGN KEY (org_id) REFERENCES organisations(id)")
    op.execute("ALTER TABLE api_keys ADD CONSTRAINT api_keys_org_id_fkey FOREIGN KEY (org_id) REFERENCES organisations(id)")
    op.execute("ALTER TABLE runs ADD CONSTRAINT runs_org_id_fkey FOREIGN KEY (org_id) REFERENCES organisations(id)")
    op.execute("ALTER TABLE user_learning_patterns ADD CONSTRAINT user_learning_patterns_org_id_fkey FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE")
    op.execute("ALTER TABLE codebase_profiles ADD CONSTRAINT codebase_profiles_org_id_fkey FOREIGN KEY (org_id) REFERENCES organisations(id)")


def downgrade() -> None:
    # Reverse process
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_org_id_fkey")
    op.execute("ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS api_keys_org_id_fkey")
    op.execute("ALTER TABLE runs DROP CONSTRAINT IF EXISTS runs_org_id_fkey")
    op.execute("ALTER TABLE user_learning_patterns DROP CONSTRAINT IF EXISTS user_learning_patterns_org_id_fkey")
    op.execute("ALTER TABLE codebase_profiles DROP CONSTRAINT IF EXISTS codebase_profiles_org_id_fkey")

    op.execute("UPDATE organisations SET id = REPLACE(id, 'org_', '') WHERE id LIKE 'org_%'")
    op.execute("UPDATE users SET org_id = REPLACE(org_id, 'org_', '') WHERE org_id LIKE 'org_%'")
    op.execute("UPDATE api_keys SET org_id = REPLACE(org_id, 'org_', '') WHERE org_id LIKE 'org_%'")
    op.execute("UPDATE runs SET org_id = REPLACE(org_id, 'org_', '') WHERE org_id LIKE 'org_%'")
    op.execute("UPDATE phase_configs SET org_id = REPLACE(org_id, 'org_', '') WHERE org_id LIKE 'org_%'")
    op.execute("UPDATE decisions SET org_id = REPLACE(org_id, 'org_', '') WHERE org_id LIKE 'org_%'")
    op.execute("UPDATE webhooks SET org_id = REPLACE(org_id, 'org_', '') WHERE org_id LIKE 'org_%'")
    op.execute("UPDATE workspaces SET org_id = REPLACE(org_id, 'org_', '') WHERE org_id LIKE 'org_%'")
    op.execute("UPDATE org_api_keys SET org_id = REPLACE(org_id, 'org_', '') WHERE org_id LIKE 'org_%'")
    op.execute("UPDATE audit_log SET org_id = REPLACE(org_id, 'org_', '') WHERE org_id LIKE 'org_%'")
    op.execute("UPDATE saml_configs SET org_id = REPLACE(org_id, 'org_', '') WHERE org_id LIKE 'org_%'")
    op.execute("UPDATE artifact_embeddings SET org_id = REPLACE(org_id, 'org_', '') WHERE org_id LIKE 'org_%'")
    op.execute("UPDATE marketplace_profiles SET org_id = REPLACE(org_id, 'org_', '') WHERE org_id LIKE 'org_%'")
    op.execute("UPDATE token_budget_records SET org_id = REPLACE(org_id, 'org_', '') WHERE org_id LIKE 'org_%'")
    op.execute("UPDATE llm_call_records SET org_id = REPLACE(org_id, 'org_', '') WHERE org_id LIKE 'org_%'")
    op.execute("UPDATE installed_plugins SET org_id = REPLACE(org_id, 'org_', '') WHERE org_id LIKE 'org_%'")
    op.execute("UPDATE llm_config SET org_id = REPLACE(org_id, 'org_', '') WHERE org_id LIKE 'org_%'")
    op.execute("UPDATE user_learning_patterns SET org_id = REPLACE(org_id, 'org_', '') WHERE org_id LIKE 'org_%'")
    op.execute("UPDATE learning_clarifications_pending SET org_id = REPLACE(org_id, 'org_', '') WHERE org_id LIKE 'org_%'")
    op.execute("UPDATE notifications SET org_id = REPLACE(org_id, 'org_', '') WHERE org_id LIKE 'org_%'")
    op.execute("UPDATE codebase_profiles SET org_id = REPLACE(org_id, 'org_', '') WHERE org_id LIKE 'org_%'")
    op.execute("UPDATE build_feedback SET org_id = REPLACE(org_id, 'org_', '') WHERE org_id LIKE 'org_%'")
    op.execute("UPDATE golden_builds SET org_id = REPLACE(org_id, 'org_', '') WHERE org_id LIKE 'org_%'")

    op.execute("ALTER TABLE users ADD CONSTRAINT users_org_id_fkey FOREIGN KEY (org_id) REFERENCES organisations(id)")
    op.execute("ALTER TABLE api_keys ADD CONSTRAINT api_keys_org_id_fkey FOREIGN KEY (org_id) REFERENCES organisations(id)")
    op.execute("ALTER TABLE runs ADD CONSTRAINT runs_org_id_fkey FOREIGN KEY (org_id) REFERENCES organisations(id)")
    op.execute("ALTER TABLE user_learning_patterns ADD CONSTRAINT user_learning_patterns_org_id_fkey FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE")
    op.execute("ALTER TABLE codebase_profiles ADD CONSTRAINT codebase_profiles_org_id_fkey FOREIGN KEY (org_id) REFERENCES organisations(id)")
