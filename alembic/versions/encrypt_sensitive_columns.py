"""encrypt_sensitive_columns

Encrypt OrgApiKey.api_key and User.mfa_secret at rest using Fernet (EncryptedText type).
Existing plaintext values are re-encrypted during upgrade; downgrade restores plaintext.

Revision ID: encrypt_sensitive_columns
Revises: revision_guardian_module
Create Date: 2026-05-31 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session

revision: str = 'encrypt_sensitive_columns'
down_revision: Union[str, None] = 'revision_guardian_module'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _get_fernet():
    import os
    from cryptography.fernet import Fernet
    key = os.environ.get("AETHER_FIELD_KEY", "")
    if not key:
        raise RuntimeError(
            "AETHER_FIELD_KEY must be set before running this migration. "
            "Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode())


def upgrade() -> None:
    bind = op.get_bind()
    fernet = _get_fernet()

    # Widen mfa_secret column from VARCHAR(64) to TEXT for PostgreSQL
    # (Fernet ciphertext is ~88+ chars; VARCHAR(64) would truncate it)
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.alter_column("users", "mfa_secret", type_=sa.Text(), existing_nullable=True)

    # Re-encrypt OrgApiKey.api_key (currently plaintext)
    rows = bind.execute(sa.text("SELECT id, api_key FROM org_api_keys")).fetchall()
    for row_id, api_key in rows:
        if api_key and not api_key.startswith("gAAAA"):  # skip already-encrypted values
            encrypted = fernet.encrypt(api_key.encode()).decode()
            bind.execute(
                sa.text("UPDATE org_api_keys SET api_key = :v WHERE id = :id"),
                {"v": encrypted, "id": row_id}
            )

    # Re-encrypt User.mfa_secret (currently plaintext)
    rows = bind.execute(sa.text("SELECT id, mfa_secret FROM users WHERE mfa_secret IS NOT NULL")).fetchall()
    for row_id, mfa_secret in rows:
        if mfa_secret and not mfa_secret.startswith("gAAAA"):
            encrypted = fernet.encrypt(mfa_secret.encode()).decode()
            bind.execute(
                sa.text("UPDATE users SET mfa_secret = :v WHERE id = :id"),
                {"v": encrypted, "id": row_id}
            )




def downgrade() -> None:
    bind = op.get_bind()
    fernet = _get_fernet()

    rows = bind.execute(sa.text("SELECT id, api_key FROM org_api_keys")).fetchall()
    for row_id, api_key in rows:
        if api_key and api_key.startswith("gAAAA"):
            plaintext = fernet.decrypt(api_key.encode()).decode()
            bind.execute(
                sa.text("UPDATE org_api_keys SET api_key = :v WHERE id = :id"),
                {"v": plaintext, "id": row_id}
            )

    rows = bind.execute(sa.text("SELECT id, mfa_secret FROM users WHERE mfa_secret IS NOT NULL")).fetchall()
    for row_id, mfa_secret in rows:
        if mfa_secret and mfa_secret.startswith("gAAAA"):
            plaintext = fernet.decrypt(mfa_secret.encode()).decode()
            bind.execute(
                sa.text("UPDATE users SET mfa_secret = :v WHERE id = :id"),
                {"v": plaintext, "id": row_id}
            )
