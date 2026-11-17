"""Everything the schema needs that `Base.metadata.create_all` alone does not give, defined ONCE.

Two paths build a database: the Alembic revisions (an existing database) and the empty-database bootstrap
(scripts/db_migrate.py -> init_db: create_all + stamp head). Objects written only as raw SQL inside a revision
(triggers, functions, extensions, extra indexes) were silently missing after a bootstrap, and tables whose model
module nobody imported were never created. Both paths now call this module, so they cannot drift:

* MODEL_MODULES / register_models(): every module that declares a table on Base.
* INDEXES: indexes that are not declared on the models.
* PG_TRIGGERS: the append-only guards of the audit ledger (PostgreSQL only).
* ensure_pgvector(): extension + column + index, when the server has pgvector.

Every statement is idempotent. `apply(conn)` takes a SYNC connection (Alembic's `op.get_bind()`, or
`await conn.run_sync(apply)` from async code). One statement per execute: asyncpg refuses multi-statement strings.
"""
from __future__ import annotations

import importlib
import logging
from typing import Iterable, Optional

from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

logger = logging.getLogger(__name__)

# Every module that declares a table on core.db.Base. tests/test_schema_ddl.py fails when a new model module is
# not listed here (it would be left out of a bootstrapped database and of Alembic autogenerate).
MODEL_MODULES = (
    "core.models",              # also registers core.scim_models, core.models_ops
    "core.billing.payments",
    "core.onboarding",
    "core.identity.portal_access",
    "core.audit.chain",
    "core.audit.checkpoints",
    "core.audit.subjects",
    "core.audit.backfill",
    "core.guardian.models",
    "prime.models",
)


def register_models() -> None:
    """Import every model module so Base.metadata is complete before create_all / autogenerate."""
    root = __name__.rsplit(".core.", 1)[0] if ".core." in __name__ else ""
    for mod in MODEL_MODULES:
        importlib.import_module(f"{root}.{mod}" if root else mod)


# name -> "table(columns)". Not declared on the models; CREATE INDEX IF NOT EXISTS on every dialect.
INDEXES = {
    "ix_users_email": "users(email)",
    "ix_users_org_id": "users(org_id)",
    "ix_api_keys_org_id": "api_keys(org_id)",
    "ix_api_keys_key_hash": "api_keys(key_hash)",
    "ix_phase_completions_run": "phase_completions(run_id, phase_name)",
    "ix_audit_log_created_at": "audit_log(created_at)",
    "ix_learning_patterns_user": "user_learning_patterns(org_id, user_id, pattern_type)",
    "ix_learning_clarif_user": "learning_clarifications_pending(org_id, user_id)",
    "ix_run_specs_run_id": "run_specs(run_id)",
    # hot per-organisation filters (revision add_hot_filter_indexes)
    "ix_runs_org_status": "runs(org_id, status)",
    "ix_runs_org_started_at": "runs(org_id, started_at)",
    "ix_notifications_org_user_unread": "notifications(org_id, user_id, is_read)",
    "ix_artifact_embeddings_org_run": "artifact_embeddings(org_id, run_id)",
    "ix_marketplace_profiles_org": "marketplace_profiles(org_id)",
    "ix_marketplace_profiles_published": "marketplace_profiles(is_published, created_at)",
    # revision add_decisions_org_status_index
    "ix_decisions_org_status_created": "decisions(org_id, status, created_at)",
}


def _guard(trigger: str, function: str, message: str, table: str, when: str, cond: str = "") -> tuple[str, ...]:
    return (
        f"CREATE OR REPLACE FUNCTION {function}() RETURNS trigger AS $$ "
        f"BEGIN RAISE EXCEPTION '{message}'; END; $$ LANGUAGE plpgsql",
        f"DROP TRIGGER IF EXISTS {trigger} ON {table}",
        f"CREATE TRIGGER {trigger} {when} ON {table} FOR EACH ROW {cond}EXECUTE FUNCTION {function}()",
    )


# trigger name -> statements. Without these the audit ledger can be rewritten with plain SQL.
PG_TRIGGERS = {
    "audit_chain_no_update_delete": _guard(
        "audit_chain_no_update_delete", "audit_chain_append_only", "audit_chain is append-only",
        "audit_chain", "BEFORE UPDATE OR DELETE"),
    "audit_chain_legacy_frozen": _guard(
        "audit_chain_legacy_frozen", "audit_chain_legacy_frozen",
        "the legacy audit chain is frozen; new entries go to per-organisation chains",
        "audit_chain", "BEFORE INSERT", "WHEN (NEW.chain_id = 'legacy') "),
    "audit_checkpoints_no_update_delete": _guard(
        "audit_checkpoints_no_update_delete", "audit_checkpoints_append_only", "audit_checkpoints is append-only",
        "audit_checkpoints", "BEFORE UPDATE OR DELETE"),
}

PGVECTOR = "pgvector"   # the name to pass in `only` for ensure_pgvector


def ensure_pgvector(conn: Connection) -> bool:
    """Extension, artifact_embeddings.embedding_vector and its cosine index. False (and nothing changed) when the
    server has no pgvector or the role may not create extensions: search then stays on the JSON column."""
    try:
        with conn.begin_nested():   # savepoint: a refused CREATE EXTENSION must not abort the caller's transaction
            conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
    except DBAPIError as exc:
        logger.warning("pgvector extension not available (%s): artifact search stays on the JSON column", exc.orig)
        return False
    conn.exec_driver_sql("ALTER TABLE artifact_embeddings ADD COLUMN IF NOT EXISTS embedding_vector vector(1536)")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_artifact_embeddings_vector_cosine "
                         "ON artifact_embeddings USING hnsw (embedding_vector vector_cosine_ops)")
    return True


def apply(conn: Connection, only: Optional[Iterable[str]] = None) -> None:
    """Create the objects named in `only` (default: all of them). Tables must already exist."""
    wanted = None if only is None else set(only)
    unknown = (wanted or set()) - set(INDEXES) - set(PG_TRIGGERS) - {PGVECTOR}
    if unknown:
        raise KeyError(f"unknown schema objects: {sorted(unknown)}")
    for name, target in INDEXES.items():
        if wanted is None or name in wanted:
            conn.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS {name} ON {target}")
    if conn.dialect.name != "postgresql":
        return
    for name, statements in PG_TRIGGERS.items():
        if wanted is None or name in wanted:
            for sql in statements:
                conn.exec_driver_sql(sql)
    if wanted is None or PGVECTOR in wanted:
        ensure_pgvector(conn)
