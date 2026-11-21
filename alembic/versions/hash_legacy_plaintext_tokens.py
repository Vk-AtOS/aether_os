"""Move the last plaintext secrets to their protected form (KAN-131).

* organisations.scim_token (plaintext): where it is the active token (no scim_token_hash yet) the bcrypt hash and
  the sha256 lookup are derived from it, so the token keeps working; then the plaintext is set to NULL everywhere.
  The column itself stays for this release (the previous application version still selects it during a rolling
  deploy); the model no longer has it and a later revision can drop it.
* webhooks.secret: rows written before the secret was Fernet-encrypted hold the plaintext signing key. They are
  encrypted with AETHER_FIELD_KEY (required only if such rows exist). The column becomes TEXT on PostgreSQL.
* questionnaire_sessions.access_token: rows written before only the sha256 was stored hold the share token itself
  (43 characters). They are replaced by their sha256 (64 hex characters), which is what a presented link is hashed to.

Not reversible for the data: a hash cannot be turned back into the token. Downgrade changes nothing (the previous
application version reads the protected forms).

Revision ID: hash_legacy_plaintext_tokens
Revises: add_org_dpa_acceptance
Create Date: 2026-11-19
"""
import hashlib
import os
from typing import Sequence, Union

import bcrypt
import sqlalchemy as sa
from alembic import op
from cryptography.fernet import Fernet

revision: str = 'hash_legacy_plaintext_tokens'
down_revision: Union[str, None] = 'add_org_dpa_acceptance'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _has_column(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    return table in insp.get_table_names() and column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()

    # a database bootstrapped from the models after this revision never had the column
    if _has_column(bind, "organisations", "scim_token"):
        rows = bind.execute(sa.text(
            "SELECT id, scim_token FROM organisations WHERE scim_token IS NOT NULL AND scim_token_hash IS NULL")).fetchall()
        for org_id, token in rows:
            if token:
                bind.execute(
                    sa.text("UPDATE organisations SET scim_token_hash = :h, scim_token_lookup = :l WHERE id = :id"),
                    {"h": bcrypt.hashpw(token.encode(), bcrypt.gensalt()).decode(), "l": _sha256(token), "id": org_id})
        bind.execute(sa.text("UPDATE organisations SET scim_token = NULL WHERE scim_token IS NOT NULL"))

    if _has_column(bind, "webhooks", "secret"):
        if bind.dialect.name == "postgresql":
            op.alter_column("webhooks", "secret", type_=sa.Text(), existing_nullable=True)
        rows = bind.execute(sa.text("SELECT id, secret FROM webhooks WHERE secret IS NOT NULL")).fetchall()
        plain = [(i, s) for i, s in rows if s and not s.startswith("gAAAA")]      # Fernet tokens start with gAAAA
        if plain:
            key = os.environ.get("AETHER_FIELD_KEY", "")
            if not key:
                raise RuntimeError(
                    f"{len(plain)} webhook(s) still hold a plaintext signing secret; AETHER_FIELD_KEY must be set "
                    "(the key the API runs with) so this migration can encrypt them.")
            fernet = Fernet(key.encode())
            for webhook_id, secret in plain:
                bind.execute(sa.text("UPDATE webhooks SET secret = :v WHERE id = :id"),
                             {"v": fernet.encrypt(secret.encode()).decode(), "id": webhook_id})

    if _has_column(bind, "questionnaire_sessions", "access_token"):
        rows = bind.execute(sa.text(
            "SELECT id, access_token FROM questionnaire_sessions WHERE length(access_token) <> 64")).fetchall()
        for session_id, token in rows:
            bind.execute(sa.text("UPDATE questionnaire_sessions SET access_token = :v WHERE id = :id"),
                         {"v": _sha256(token), "id": session_id})


def downgrade() -> None:
    pass    # see the module docstring: nothing to restore, and the previous version reads the protected forms
