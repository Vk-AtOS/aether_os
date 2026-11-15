# AetherOS Data Model

**Generated from the SQLAlchemy metadata, not written by hand.** Source commit: `e5c23fd`. Method: import the
model modules and read `Base.metadata.tables` (`core/db.py:32` defines `Base`). The throw-away script is
`/private/tmp/claude-501/-Users-apple/1a57cd35-efca-4a1e-b634-a519eaf0e507/scratchpad/a_docs/docs_b/dump_models.py`
(not in the repository). Result: **52 tables, 483 columns.** The previous version of this file listed 22 tables.

Files that define tables (count of tables per file, from the "Model" lines below):

- `core/models.py`: 34
- `core/scim_models.py`: 2 (imported by `core/models.py:573`)
- `core/audit/`: `chain.py` 1, `checkpoints.py` 1, `subjects.py` 3, `backfill.py` 1
- `core/identity/portal_access.py`: 2 (`portal_tokens`, `portal_approvals`)
- `core/guardian/models.py`: 2
- `core/billing/payments.py`: 1
- `core/onboarding.py`: 1
- `prime/models.py`: 4

A table in a module that nothing imports is missing from `Base.metadata`. `alembic/env.py` imports only
`core.models` (and the `scim_models` it pulls in). Whether the other modules are imported through
`core.models` or through the gateway before Alembic runs: not verified. When generating this file, a module
list was imported by hand, so the 52 count assumes all of the files above are loaded.

## How the schema is created

- SQLite (development, tests): `init_db()` runs `Base.metadata.create_all` plus extra `CREATE INDEX IF NOT EXISTS`
  statements (`core/db.py:208-268`).
- PostgreSQL: Alembic owns the schema. Startup refuses a database that is not at the Alembic head and refuses one
  without the three ledger triggers `audit_chain_no_update_delete`, `audit_chain_legacy_frozen` and
  `audit_checkpoints_no_update_delete` (`core/db.py:166-205`), unless `AETHER_DB_CREATE_ALL` is set.
- Alembic: 79 revision files in `alembic/versions/`, one head: `merge_r2_heads` (read with
  `ScriptDirectory.get_heads()` at commit `e5c23fd`). **The migrations have never been run against a real
  PostgreSQL in this work: not measured.** Whether `alembic upgrade head` from an empty database succeeds: not
  verified. `deploy/deploy.sh` does not rely on it for an empty database: it creates the tables and stamps
  (`scripts/db_migrate.py`).
- Drift found by reading `alembic/versions/` against the metadata (a grep for `create_table`, so it can miss
  tables created by raw SQL): no migration creates `audit_log`, `llm_call_records`, `run_specs` or
  `user_learning_patterns` (migrations only alter them); migration `revision_4d5c94389944` creates a table
  `org_code_profiles` that no model defines. How those four tables get created on a fresh database through
  Alembic alone: not verified.

## Conventions seen in the models

- `org_id` is a column on 34 of the 52 tables. Tables without it: `organisations`, `events`, `snapshots`,
  `phase_completions`, `run_metadata`, `llm_cache_entries`, `run_specs`, `pipeline_events`, `llm_traces`,
  `questionnaire_sessions`, `audit_checkpoints`, `audit_chain`, `audit_org_peppers`, `audit_subjects`,
  `audit_erasures`, `audit_backfill`, `guardian_snapshots`, `prime_delegations`. Several of these reach an
  organisation through `run_id`, and `audit_chain` carries the organisation in its payload (`chain_id`).
- Only these foreign keys exist in the metadata: `users`, `api_keys`, `runs`, `global_patterns`,
  `user_learning_patterns`, `codebase_profiles` -> `organisations.id`; `events`, `snapshots`, `phase_completions`,
  `learning_clarifications_pending`, `run_specs`, `build_feedback`, `pipeline_events`, `llm_traces`,
  `questionnaire_sessions` -> `runs.id`; `user_learning_patterns.user_id` -> `users.id`. Every other `org_id` or
  `run_id` column is a plain string with no database foreign key.
- Timestamps are a mix of `FLOAT` (Unix time) and `DATETIME`; see each table.
- Two columns use the encrypted type `EncryptedText` (Fernet, key `AETHER_FIELD_KEY`, `core/encryption.py`).
- Audit: `audit_log` is the older table with a `prev_hash` column; `audit_chain` is the hash-linked ledger, one
  chain per organisation (`chain_id`), with checkpoints, per-organisation peppers and erasure tombstones
  (`core/audit/chain.py` module docstring). The no-update, no-delete rule for the ledger tables is enforced by
  PostgreSQL triggers created in migrations, not by the models.

## Table reference

Each section: model class and file, first paragraph of its docstring if it has one, then columns (type,
nullability, primary or foreign key, default) and indexes and constraints. "generated in Python" means a Python
callable supplies the default. `server:` marks a database-side default.

### `api_keys`

Model `APIKey` at `core/models.py:73`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `org_id` | VARCHAR(50) | no | FK organisations.id |  |
| `key_hash` | VARCHAR(255) | no |  |  |
| `name` | VARCHAR(255) | no |  |  |
| `last_used_at` | FLOAT | yes |  |  |
| `is_active` | BOOLEAN | no |  | `True` |
| `created_at` | DATETIME | no |  | `_utcnow()` |

### `artifact_embeddings`

Model `ArtifactEmbedding` at `core/models.py:266`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `run_id` | VARCHAR(36) | no |  |  |
| `org_id` | VARCHAR(50) | no |  |  |
| `file_path` | TEXT | no |  |  |
| `content_hash` | VARCHAR(255) | no |  |  |
| `embedding` | JSON | yes |  |  |
| `created_at` | DATETIME | no |  | `_utcnow()` |

### `audit_backfill`

Model `AuditBackfill` at `core/audit/backfill.py:40`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `audit_log_id` | VARCHAR(36) | no | PK |  |
| `entry_hash` | VARCHAR(64) | no |  |  |
| `imported_at` | FLOAT | no |  |  |

### `audit_chain`

Model `AuditChainEntry` at `core/audit/chain.py:77`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `seq` | INTEGER | no | PK |  |
| `chain_id` | VARCHAR(64) | no |  |  |
| `chain_seq` | INTEGER | yes |  |  |
| `timestamp` | FLOAT | no |  |  |
| `actor` | VARCHAR(255) | no |  |  |
| `action` | VARCHAR(255) | no |  |  |
| `payload` | TEXT | no |  |  |
| `prev_hash` | VARCHAR(64) | no |  |  |
| `entry_hash` | VARCHAR(64) | no | unique |  |

- Index `ix_audit_chain_chain_row` on (chain_id, seq)
- Unique `unnamed` on (entry_hash)
- Unique `uq_audit_chain_position` on (chain_id, chain_seq)
- Unique `uq_audit_chain_prev` on (chain_id, prev_hash)

### `audit_checkpoints`

Model `AuditCheckpoint` at `core/audit/checkpoints.py:41`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | INTEGER | no | PK |  |
| `chain_id` | VARCHAR(64) | no | indexed |  |
| `chain_seq` | INTEGER | no |  |  |
| `head_hash` | VARCHAR(64) | no |  |  |
| `created_at` | FLOAT | no |  |  |
| `key_id` | VARCHAR(32) | no |  |  |
| `signature` | VARCHAR(128) | no |  |  |

- Index `ix_audit_checkpoints_chain_id` on (chain_id)
- Unique `uq_audit_checkpoint_position` on (chain_id, chain_seq)

### `audit_erasures`

Model `AuditErasure` at `core/audit/subjects.py:62`. Tombstones: which values were erased, so raw copies in old rows can be hidden. A row with kind NULL means the whole organisation was erased.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | INTEGER | no | PK |  |
| `chain_id` | VARCHAR(64) | no | indexed |  |
| `kind` | VARCHAR(16) | yes |  |  |
| `value_hmac` | VARCHAR(64) | yes |  |  |
| `subject_id` | VARCHAR(36) | yes |  |  |
| `erased_at` | FLOAT | no |  |  |

- Index `ix_audit_erasures_chain_id` on (chain_id)

### `audit_log`

Model `AuditLog` at `core/models.py:233`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `org_id` | VARCHAR(50) | no | indexed |  |
| `user_id` | VARCHAR(36) | no |  |  |
| `action` | VARCHAR(255) | no |  |  |
| `resource_type` | VARCHAR(100) | no |  |  |
| `resource_id` | VARCHAR(255) | no |  |  |
| `log_metadata` | TEXT | yes |  |  |
| `ip_address` | VARCHAR(45) | yes |  |  |
| `created_at` | FLOAT | no |  | `time()` |
| `prev_hash` | VARCHAR(64) | yes |  |  |

- Index `ix_audit_log_org_id` on (org_id)

### `audit_org_peppers`

Model `AuditOrgPepper` at `core/audit/subjects.py:44`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `chain_id` | VARCHAR(64) | no | PK |  |
| `pepper` | VARCHAR(64) | no |  |  |
| `created_at` | FLOAT | no |  |  |

### `audit_subjects`

Model `AuditSubject` at `core/audit/subjects.py:51`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK |  |
| `chain_id` | VARCHAR(64) | no | indexed |  |
| `kind` | VARCHAR(16) | no |  |  |
| `value_hmac` | VARCHAR(64) | no |  |  |
| `value` | TEXT | no |  |  |
| `created_at` | FLOAT | no |  |  |

- Index `ix_audit_subjects_chain_id` on (chain_id)
- Unique `uq_audit_subject_value` on (chain_id, kind, value_hmac)

### `billing_payments`

Model `BillingPayment` at `core/billing/payments.py:35`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `provider` | VARCHAR(20) | no |  |  |
| `order_id` | VARCHAR(100) | no |  |  |
| `payment_id` | VARCHAR(100) | no |  |  |
| `org_id` | VARCHAR(50) | no | indexed |  |
| `plan` | VARCHAR(50) | no |  |  |
| `amount` | INTEGER | yes |  |  |
| `created_at` | FLOAT | no |  | `time()` |

- Index `ix_billing_payments_org_id` on (org_id)
- Unique `uq_billing_payments_order` on (provider, order_id)
- Unique `uq_billing_payments_payment` on (provider, payment_id)

### `build_feedback`

Model `BuildFeedback` at `core/models.py:486`. User star-rating and tag feedback on a completed pipeline run.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `run_id` | VARCHAR(36) | no | FK runs.id ondelete=CASCADE, indexed |  |
| `org_id` | VARCHAR(50) | no | indexed |  |
| `user_id` | VARCHAR(36) | yes |  |  |
| `rating` | INTEGER | no |  |  |
| `tags` | JSON | yes |  |  |
| `comment` | TEXT | yes |  |  |
| `created_at` | DATETIME | no |  | `_utcnow()` |

- Index `ix_build_feedback_org_id` on (org_id)
- Index `ix_build_feedback_run_id` on (run_id)
- Unique `uq_build_feedback_run_user` on (run_id, user_id)

### `codebase_profiles`

Model `CodebaseProfile` at `core/models.py:472`. Imported codebase profile for use as additional context in pipeline runs.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `org_id` | VARCHAR(50) | no | FK organisations.id, indexed |  |
| `repo_url` | VARCHAR(512) | no |  |  |
| `repo_name` | VARCHAR(256) | no |  |  |
| `detected_stack` | JSON | yes |  |  |
| `file_tree` | JSON | yes |  |  |
| `summary` | TEXT | yes |  |  |
| `created_at` | DATETIME | no |  | generated in Python |

- Index `ix_codebase_profiles_org_id` on (org_id)

### `decisions`

Model `Decision` at `core/models.py:172`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `run_id` | VARCHAR(36) | no | indexed |  |
| `org_id` | VARCHAR(50) | no | indexed |  |
| `decision_type` | VARCHAR(100) | no |  |  |
| `title` | VARCHAR(255) | no |  |  |
| `what` | TEXT | no |  |  |
| `why` | TEXT | no |  |  |
| `alternatives` | JSON | yes |  |  |
| `impact` | TEXT | yes |  |  |
| `phase` | VARCHAR(100) | yes |  |  |
| `status` | VARCHAR(50) | no |  | `'pending'` |
| `human_choice` | VARCHAR(100) | yes |  |  |
| `timeout_seconds` | INTEGER | no |  | `300` |
| `created_at` | DATETIME | no |  | `_utcnow()` |
| `decided_at` | DATETIME | yes |  |  |

- Index `ix_decisions_org_id` on (org_id)
- Index `ix_decisions_org_status_created` on (org_id, status, created_at)
- Index `ix_decisions_run_id` on (run_id)

### `events`

Model `Event` at `core/models.py:122`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `run_id` | VARCHAR(36) | no | FK runs.id, indexed |  |
| `agent` | VARCHAR(255) | yes |  |  |
| `action` | VARCHAR(255) | yes |  |  |
| `detail` | TEXT | yes |  |  |
| `timestamp` | FLOAT | yes |  |  |

- Index `ix_events_run_id` on (run_id)

### `global_patterns`

Model `GlobalPattern` at `core/models.py:293`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `org_id` | VARCHAR(50) | yes | FK organisations.id, indexed |  |
| `domain` | VARCHAR(255) | no |  |  |
| `pattern_name` | VARCHAR(255) | no |  |  |
| `pattern_type` | VARCHAR(100) | no |  |  |
| `success_rate` | FLOAT | no |  | `0.0` |
| `usage_count` | INTEGER | no |  | `0` |
| `avg_quality_score` | FLOAT | no |  | `0.0` |
| `last_updated` | DATETIME | no |  | `_utcnow()` |

- Index `ix_global_patterns_org_id` on (org_id)

### `golden_builds`

Model `GoldenBuild` at `core/models.py:502`. Curated best-in-class build examples used as few-shot context for LLM prompts.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `run_id` | VARCHAR(36) | no | indexed |  |
| `org_id` | VARCHAR(50) | no | indexed |  |
| `domain` | VARCHAR(50) | no | indexed |  |
| `project_name` | VARCHAR(255) | no |  |  |
| `prompt_summary` | TEXT | yes |  |  |
| `quality_score` | FLOAT | yes |  |  |
| `user_rating` | FLOAT | yes |  |  |
| `p04_sample` | TEXT | yes |  |  |
| `p05_sample` | TEXT | yes |  |  |
| `entity_count` | INTEGER | yes |  |  |
| `domain_ir_summary` | JSON | yes |  |  |
| `is_active` | BOOLEAN | no | indexed | `True` |
| `created_at` | DATETIME | no |  | `_utcnow()` |

- Index `ix_golden_builds_domain` on (domain)
- Index `ix_golden_builds_is_active` on (is_active)
- Index `ix_golden_builds_org_id` on (org_id)
- Index `ix_golden_builds_run_id` on (run_id)
- Unique `uq_golden_build_run` on (run_id)

### `guardian_events`

Model `GuardianEvent` at `core/guardian/models.py:11`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `event_type` | VARCHAR(50) | no | indexed |  |
| `severity` | VARCHAR(20) | no | indexed |  |
| `source_ip` | VARCHAR(64) | yes |  |  |
| `endpoint` | VARCHAR(512) | yes |  |  |
| `detail` | JSON | yes |  |  |
| `org_id` | VARCHAR(50) | yes | indexed |  |
| `resolved` | BOOLEAN | no |  | `False` |
| `created_at` | DATETIME | no | indexed | generated in Python |
| `resolved_at` | DATETIME | yes |  |  |

- Index `ix_guardian_events_created_at` on (created_at)
- Index `ix_guardian_events_event_type` on (event_type)
- Index `ix_guardian_events_org_id` on (org_id)
- Index `ix_guardian_events_severity` on (severity)

### `guardian_snapshots`

Model `GuardianSnapshot` at `core/guardian/models.py:28`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `created_at` | DATETIME | no | indexed | generated in Python |
| `snapshot_path` | TEXT | no |  |  |
| `size_bytes` | INTEGER | no |  | `0` |
| `integrity_hash` | VARCHAR(64) | no |  |  |
| `trigger` | VARCHAR(30) | no |  | `'scheduled'` |
| `status` | VARCHAR(20) | no |  | `'ok'` |
| `note` | TEXT | yes |  |  |
| `db_backend` | VARCHAR(20) | no |  | `'sqlite'` |

- Index `ix_guardian_snapshots_created_at` on (created_at)

### `installed_plugins`

Model `InstalledPluginRecord` at `core/models.py:358`. Installed plugins per org - replaces per-process SQLite file.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `org_id` | VARCHAR(50) | no | indexed |  |
| `plugin_id` | VARCHAR(100) | no |  |  |
| `config_json` | TEXT | yes |  |  |
| `installed_at` | FLOAT | no |  | `time()` |
| `last_tested_at` | FLOAT | yes |  |  |
| `test_status` | VARCHAR(20) | yes |  |  |

- Index `ix_installed_plugins_org_id` on (org_id)
- Unique `uq_installed_plugin_org_plugin` on (org_id, plugin_id)

### `learning_clarifications_pending`

Model `LearningClarificationPending` at `core/models.py:415`. Project-scoped clarification questions pending user answer.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `org_id` | VARCHAR(50) | no | indexed |  |
| `user_id` | VARCHAR(36) | no | indexed |  |
| `run_id` | VARCHAR(36) | yes | FK runs.id ondelete=SET NULL |  |
| `question` | TEXT | no |  |  |
| `question_type` | VARCHAR(32) | no |  | `'clarification'` |
| `context` | JSON | yes |  |  |
| `answered_at` | DATETIME | yes |  |  |
| `answer` | JSON | yes |  |  |
| `created_at` | DATETIME | no |  | `_utcnow()` |
| `expires_at` | DATETIME | yes |  |  |

- Index `ix_learning_clarifications_pending_org_id` on (org_id)
- Index `ix_learning_clarifications_pending_user_id` on (user_id)

### `llm_cache_entries`

Model `LLMCacheEntry` at `core/models.py:309`. Shared LLM response cache - replaces per-process SQLite file.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `cache_key` | VARCHAR(64) | no | PK |  |
| `task_type` | VARCHAR(64) | no |  |  |
| `response` | TEXT | no |  |  |
| `prompt_tokens` | INTEGER | no |  | `0` |
| `hit_count` | INTEGER | no |  | `0` |
| `created_at` | FLOAT | no |  | `time()` |
| `last_hit_at` | FLOAT | no |  | `time()` |

### `llm_call_records`

Model `LLMCallRecord` at `core/models.py:343`. Individual LLM call record for cost/usage tracking (replaces billing.db).

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `org_id` | VARCHAR(50) | yes | indexed |  |
| `project_id` | VARCHAR(255) | no | indexed |  |
| `phase` | VARCHAR(100) | no |  |  |
| `model` | VARCHAR(100) | no |  |  |
| `input_tokens` | INTEGER | no |  | `0` |
| `output_tokens` | INTEGER | no |  | `0` |
| `cost_usd` | FLOAT | no |  | `0.0` |
| `created_at` | FLOAT | no |  | `time()` |

- Index `ix_llm_call_records_org_id` on (org_id)
- Index `ix_llm_call_records_project_id` on (project_id)

### `llm_config`

Model `LlmConfig` at `core/models.py:373`. Per-org (or global) LLM provider configuration persisted in DB.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `org_id` | VARCHAR(50) | yes | indexed |  |
| `provider` | VARCHAR(64) | no |  | `'openrouter'` |
| `heavy_model` | VARCHAR(256) | yes |  |  |
| `light_model` | VARCHAR(256) | yes |  |  |
| `prefer_paid` | BOOLEAN | no |  | `False` |
| `council_enabled` | BOOLEAN | no |  | `True` |
| `council_strict_mode` | BOOLEAN | no |  | `False` |
| `langsmith_enabled` | BOOLEAN | no |  | `False` |
| `langsmith_project` | VARCHAR(255) | no |  | `'aetheros-factory'` |
| `bedrock_enabled` | BOOLEAN | no |  | `False` |
| `bedrock_region` | VARCHAR(50) | no |  | `'us-east-1'` |
| `bedrock_model_heavy` | VARCHAR(255) | no |  | `'us.anthropic.claude-sonnet-4-6'` |
| `bedrock_model_light` | VARCHAR(255) | no |  | `'us.anthropic.claude-haiku-4-5-20251001-v1:0'` |
| `updated_at` | FLOAT | yes |  | `time()` |

- Index `ix_llm_config_org_id` on (org_id)

### `llm_traces`

Model `LLMTrace` at `core/models.py:534`. Deep observability trace for every LLM call attempt.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `run_id` | VARCHAR(36) | yes | FK runs.id ondelete=CASCADE, indexed |  |
| `phase` | VARCHAR(50) | no | indexed |  |
| `task_type` | VARCHAR(100) | yes |  |  |
| `model` | VARCHAR(100) | yes |  |  |
| `prompt` | TEXT | yes |  |  |
| `raw_response` | TEXT | yes |  |  |
| `parsed_ok` | BOOLEAN | no |  | `True` |
| `error` | TEXT | yes |  |  |
| `attempt` | INTEGER | no |  | `1` |
| `duration_ms` | INTEGER | no |  | `0` |
| `tokens_in` | INTEGER | no |  | `0` |
| `tokens_out` | INTEGER | no |  | `0` |
| `created_at` | DATETIME | no | indexed | `_utcnow()` |

- Index `ix_llm_traces_created_at` on (created_at)
- Index `ix_llm_traces_phase` on (phase)
- Index `ix_llm_traces_run_id` on (run_id)

### `marketplace_profiles`

Model `MarketplaceProfile` at `core/models.py:279`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `org_id` | VARCHAR(50) | no |  |  |
| `name` | VARCHAR(255) | no |  |  |
| `base_domain` | VARCHAR(255) | no |  |  |
| `description` | TEXT | yes |  |  |
| `price_usd` | FLOAT | no |  | `0.0` |
| `profile_yaml` | TEXT | no |  |  |
| `is_published` | BOOLEAN | no |  | `False` |
| `usage_count` | INTEGER | no |  | `0` |
| `created_at` | DATETIME | no |  | `_utcnow()` |

### `notification_prefs`

Model `NotificationPref` at `core/models.py:458`. Which notification events reach whom, per channel. user_id '' is the organisation default; a user's row overrides it. No row = the built-in default (everything on), so existing behaviour is unchanged.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `org_id` | VARCHAR(50) | no | indexed |  |
| `user_id` | VARCHAR(36) | no |  | `''` |
| `event_type` | VARCHAR(64) | no |  |  |
| `in_app` | BOOLEAN | no |  | `True` |
| `email` | BOOLEAN | no |  | `True` |

- Index `ix_notification_prefs_org_id` on (org_id)
- Unique `uq_notification_prefs` on (org_id, user_id, event_type)

### `notifications`

Model `Notification` at `core/models.py:443`. In-app notification for org members.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `org_id` | VARCHAR(50) | no | indexed |  |
| `user_id` | VARCHAR(36) | yes | indexed |  |
| `type` | VARCHAR(64) | no |  |  |
| `title` | VARCHAR(255) | no |  |  |
| `message` | TEXT | yes |  |  |
| `link` | VARCHAR(512) | yes |  |  |
| `is_read` | BOOLEAN | no |  | `False` |
| `created_at` | FLOAT | no |  | `time()` |

- Index `ix_notifications_org_id` on (org_id)
- Index `ix_notifications_user_id` on (user_id)

### `org_api_keys`

Model `OrgApiKey` at `core/models.py:219`. Per-org LLM provider API key storage (replaces shared .env approach).

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `org_id` | VARCHAR(50) | no | indexed |  |
| `provider` | VARCHAR(64) | no |  |  |
| `api_key` | TEXT (EncryptedText) | no |  |  |
| `updated_at` | FLOAT | no |  | `time()` |
| `updated_by` | VARCHAR(36) | yes |  |  |

- Index `ix_org_api_keys_org_id` on (org_id)
- Unique `uq_org_provider` on (org_id, provider)

### `org_onboarding`

Model `OnboardingDismissal` at `core/onboarding.py:21`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `org_id` | VARCHAR(50) | no | PK |  |
| `dismissed_by` | VARCHAR(36) | no |  |  |
| `dismissed_at` | DATETIME | no |  | generated in Python |

### `organisations`

Model `Organisation` at `core/models.py:15`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(50) | no | PK | generated in Python |
| `name` | VARCHAR(255) | no |  |  |
| `slug` | VARCHAR(255) | no | unique |  |
| `plan` | VARCHAR(50) | no |  | `'trial'` |
| `created_at` | DATETIME | no |  | `_utcnow()` |
| `trial_runs_used` | INTEGER | no |  | `0` |
| `trial_runs_limit` | INTEGER | no |  | `3` |
| `storage_used_mb` | FLOAT | no |  | `0.0` |
| `autonomous_mode` | BOOLEAN | no |  | `False` |
| `data_region` | VARCHAR(20) | no |  | `'global'` |
| `scim_token` | VARCHAR(128) | yes |  |  |
| `scim_token_hash` | VARCHAR(128) | yes |  |  |
| `scim_token_lookup` | VARCHAR(64) | yes | indexed |  |
| `stripe_customer_id` | VARCHAR(64) | yes |  |  |
| `plan_period_end` | FLOAT | yes |  |  |
| `is_deleted` | BOOLEAN | no |  | `False` |
| `deleted_at` | DATETIME | yes |  |  |
| `updated_at` | DATETIME | yes |  |  |
| `llm_monthly_cap_usd` | FLOAT | yes |  |  |
| `llm_disabled` | BOOLEAN | no |  | `False` |
| `require_admin_mfa` | BOOLEAN | no |  | `False` |
| `admin_mfa_grace_until` | FLOAT | yes |  |  |

- Index `ix_organisations_scim_token_lookup` on (scim_token_lookup)
- Unique `unnamed` on (slug)

### `phase_completions`

Model `PhaseCompletion` at `core/models.py:145`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `run_id` | VARCHAR(36) | no | PK, FK runs.id |  |
| `phase_name` | VARCHAR(255) | no | PK |  |
| `status` | VARCHAR(50) | yes |  |  |
| `duration_s` | FLOAT | yes |  |  |
| `updated_at` | FLOAT | yes |  |  |

### `phase_configs`

Model `PhaseConfig` at `core/models.py:156`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `org_id` | VARCHAR(50) | no | PK |  |
| `phase_name` | VARCHAR(255) | no | PK |  |
| `enabled` | INTEGER | no |  | `1` |
| `priority` | VARCHAR(50) | no |  | `'normal'` |
| `updated_at` | FLOAT | yes |  |  |

### `pipeline_events`

Model `PipelineEvent` at `core/models.py:523`. Persistent record of every pipeline event (Fix 24).

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `run_id` | VARCHAR(36) | no | FK runs.id ondelete=CASCADE, indexed |  |
| `event_type` | VARCHAR(100) | no | indexed |  |
| `payload` | JSON | yes |  |  |
| `created_at` | DATETIME | no | indexed | `_utcnow()` |

- Index `ix_pipeline_events_created_at` on (created_at)
- Index `ix_pipeline_events_event_type` on (event_type)
- Index `ix_pipeline_events_run_id` on (run_id)

### `portal_approvals`

Model `PortalApproval` at `core/identity/portal_access.py:54`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `org_id` | VARCHAR(50) | no | indexed |  |
| `project_id` | VARCHAR(128) | no | indexed |  |
| `approved` | BOOLEAN | no |  |  |
| `comment` | TEXT | yes |  |  |
| `actor_kind` | VARCHAR(20) | no |  |  |
| `actor_id` | VARCHAR(64) | no |  |  |
| `actor_label` | VARCHAR(255) | no |  | `''` |
| `applied_to` | VARCHAR(40) | yes |  |  |
| `created_at` | FLOAT | no |  |  |
| `prev_approval_id` | VARCHAR(48) | no |  | `''` |

- Index `ix_portal_approvals_org_id` on (org_id)
- Index `ix_portal_approvals_project_id` on (project_id)
- Unique `uq_portal_approvals_actor_chain` on (project_id, actor_kind, actor_id, prev_approval_id)

### `portal_tokens`

Model `PortalToken` at `core/identity/portal_access.py:38`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `org_id` | VARCHAR(50) | no | indexed |  |
| `project_id` | VARCHAR(128) | no | indexed |  |
| `token_hash` | VARCHAR(64) | no | unique |  |
| `label` | VARCHAR(120) | no |  | `''` |
| `created_by` | VARCHAR(64) | no |  |  |
| `created_at` | FLOAT | no |  |  |
| `expires_at` | FLOAT | no |  |  |
| `revoked_at` | FLOAT | yes |  |  |
| `revoked_by` | VARCHAR(64) | yes |  |  |
| `last_used_at` | FLOAT | yes |  |  |

- Index `ix_portal_tokens_org_id` on (org_id)
- Index `ix_portal_tokens_project_id` on (project_id)
- Unique `unnamed` on (token_hash)

### `prime_corrections`

Model `PrimeCorrection` at `prime/models.py:91`. What a person changed or refused before approving (KAN-24): the agent's proposal, the correction and why. Personal data is pseudonymised before it is stored; every row belongs to one organisation and is never read across organisations.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `org_id` | VARCHAR(50) | no | indexed |  |
| `agent` | VARCHAR(128) | no |  |  |
| `action_type` | VARCHAR(64) | no |  |  |
| `ref` | VARCHAR(80) | no | unique |  |
| `input_summary` | TEXT | no |  |  |
| `proposed` | TEXT | no |  |  |
| `corrected` | TEXT | no |  |  |
| `reason` | TEXT | no |  |  |
| `approver_role` | VARCHAR(32) | yes |  |  |
| `on_behalf_of` | VARCHAR(255) | no | indexed |  |
| `requested_by` | VARCHAR(255) | no |  |  |
| `corrected_by` | VARCHAR(255) | no |  |  |
| `good_example` | BOOLEAN | no |  | `False` |
| `used_count` | INTEGER | no |  | `0` |
| `changed_outcome_count` | INTEGER | no |  | `0` |
| `created_at` | DATETIME | no |  | `_utcnow()` |

- Index `ix_prime_corrections_lookup` on (org_id, agent, action_type)
- Index `ix_prime_corrections_on_behalf_of` on (on_behalf_of)
- Index `ix_prime_corrections_org_id` on (org_id)
- Unique `unnamed` on (ref)

### `prime_delegations`

Model `PrimeDelegation` at `prime/models.py:15`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `grantor` | VARCHAR(255) | no | indexed |  |
| `deputy` | VARCHAR(255) | no |  |  |
| `scope` | JSON | no |  |  |
| `max_amount` | VARCHAR(32) | yes |  |  |
| `currency` | VARCHAR(3) | yes |  |  |
| `autonomy` | INTEGER | no |  |  |
| `valid_from` | DATETIME | no |  |  |
| `valid_until` | DATETIME | no |  |  |
| `revoked_at` | DATETIME | yes |  |  |
| `revoked_by` | VARCHAR(255) | yes |  |  |
| `created_at` | DATETIME | no |  | `_utcnow()` |

- Index `ix_prime_delegations_grantor` on (grantor)

### `prime_org_limits`

Model `PrimeOrgLimits` at `prime/models.py:34`. Per-organisation Prime limits. No row means the defaults in prime/authz.py.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `org_id` | VARCHAR(50) | no | PK |  |
| `payment_ceiling` | VARCHAR(32) | no |  |  |
| `max_delegation_days` | INTEGER | no |  |  |
| `request_ttl_hours` | INTEGER | no |  | `72` |
| `updated_by` | VARCHAR(255) | no |  |  |
| `updated_at` | DATETIME | no |  | `_utcnow()` |

### `prime_requests`

Model `PrimeRequest` at `prime/models.py:47`. An action Prime was asked to carry out that reached a person or an executor.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK |  |
| `org_id` | VARCHAR(50) | no | indexed |  |
| `action_type` | VARCHAR(64) | no |  |  |
| `on_behalf_of` | VARCHAR(255) | no | indexed |  |
| `requested_by` | VARCHAR(255) | no |  |  |
| `amount` | VARCHAR(32) | yes |  |  |
| `currency` | VARCHAR(3) | yes |  |  |
| `params` | JSON | no |  |  |
| `executor` | VARCHAR(64) | no |  |  |
| `delegation_id` | VARCHAR(36) | no | indexed |  |
| `deputy` | VARCHAR(255) | no | indexed |  |
| `outcome` | VARCHAR(32) | no |  |  |
| `reason` | TEXT | no |  |  |
| `request_hash` | VARCHAR(64) | no | unique |  |
| `status` | VARCHAR(16) | no | indexed |  |
| `decided_by` | VARCHAR(255) | yes |  |  |
| `decided_at` | DATETIME | yes |  |  |
| `decision_reason` | TEXT | yes |  |  |
| `decided_hash` | VARCHAR(64) | yes |  |  |
| `exec_status` | VARCHAR(20) | yes |  |  |
| `exec_started_at` | DATETIME | yes |  |  |
| `exec_result` | JSON | yes |  |  |
| `created_at` | DATETIME | no |  |  |
| `expires_at` | DATETIME | no |  |  |
| `revision` | INTEGER | no |  | `0` |
| `edited_by` | JSON | yes |  |  |
| `reminded_at` | DATETIME | yes |  |  |
| `expiry_notified_at` | DATETIME | yes |  |  |

- Index `ix_prime_requests_delegation_id` on (delegation_id)
- Index `ix_prime_requests_deputy` on (deputy)
- Index `ix_prime_requests_on_behalf_of` on (on_behalf_of)
- Index `ix_prime_requests_org_id` on (org_id)
- Index `ix_prime_requests_status` on (status)
- Index `ix_prime_requests_status_expires` on (status, expires_at)
- Unique `unnamed` on (request_hash)

### `questionnaire_sessions`

Model `QuestionnaireSession` at `core/models.py:554`. Interactive phase-by-phase questionnaire session for guided pipeline mode.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `run_id` | VARCHAR(36) | no | FK runs.id ondelete=CASCADE, indexed |  |
| `stage_id` | VARCHAR(50) | no |  |  |
| `status` | VARCHAR(20) | no |  | `'pending'` |
| `access_token` | VARCHAR(64) | no | unique, indexed |  |
| `token_expires_at` | DATETIME | no |  |  |
| `respondent_email` | VARCHAR(255) | yes |  |  |
| `respondent_name` | VARCHAR(255) | yes |  |  |
| `agency_name` | VARCHAR(255) | yes |  |  |
| `agency_logo_url` | VARCHAR(512) | yes |  |  |
| `questions` | JSON | no |  | `list()` |
| `answers` | JSON | yes |  |  |
| `submitted_at` | DATETIME | yes |  |  |
| `created_at` | DATETIME | no |  | generated in Python |

- Index `ix_questionnaire_sessions_access_token` on (access_token) unique
- Index `ix_questionnaire_sessions_run_id` on (run_id)

### `run_metadata`

Model `RunMetadata` at `core/models.py:165`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `run_id` | VARCHAR(36) | no | PK |  |
| `priority` | VARCHAR(50) | no |  | `'normal'` |
| `updated_at` | FLOAT | yes |  |  |

### `run_specs`

Model `RunSpec` at `core/models.py:432`. Stores frontend/backend spec JSON attached to a run (from Builder tabs).

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `run_id` | VARCHAR(36) | no | PK, FK runs.id ondelete=CASCADE |  |
| `spec_type` | VARCHAR(32) | no | PK |  |
| `spec` | JSON | no |  | `dict()` |
| `created_at` | DATETIME | no |  | `_utcnow()` |
| `updated_at` | DATETIME | no |  | `_utcnow()` |

### `runs`

Model `Run` at `core/models.py:86`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK |  |
| `org_id` | VARCHAR(50) | yes | FK organisations.id, indexed |  |
| `command` | TEXT | yes |  |  |
| `status` | VARCHAR(50) | yes | indexed |  |
| `started_at` | FLOAT | yes | indexed |  |
| `finished_at` | FLOAT | yes |  |  |
| `live_url` | TEXT | yes |  |  |
| `cost` | FLOAT | no |  | `0.0` |
| `run_version` | INTEGER | no |  | `1` |
| `parallel_run_group_id` | VARCHAR(36) | yes |  |  |
| `self_test_report` | TEXT | yes |  |  |
| `raw_input` | TEXT | yes |  |  |
| `requirement` | TEXT | yes |  |  |
| `project_name` | VARCHAR(512) | yes |  |  |
| `domain` | VARCHAR(100) | yes |  | `'general'` |
| `client_id` | VARCHAR(255) | yes |  |  |
| `user_id` | VARCHAR(36) | yes | indexed |  |
| `current_phase` | VARCHAR(100) | yes |  |  |
| `message` | TEXT | yes |  |  |
| `phases` | JSON | yes |  |  |
| `council_preflight` | JSON | yes |  |  |
| `council_delivery` | JSON | yes |  |  |
| `parent_run_id` | VARCHAR(36) | yes | indexed |  |
| `branch_phase` | VARCHAR(100) | yes |  |  |
| `quality_score` | INTEGER | yes |  |  |
| `checkpoint_data` | JSON | yes |  |  |

- Index `ix_runs_org_id` on (org_id)
- Index `ix_runs_parent_run_id` on (parent_run_id)
- Index `ix_runs_started_at` on (started_at)
- Index `ix_runs_status` on (status)
- Index `ix_runs_user_id` on (user_id)

### `saml_configs`

Model `SamlConfig` at `core/models.py:247`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `org_id` | VARCHAR(50) | no |  |  |
| `idp_entity_id` | VARCHAR(512) | no |  |  |
| `idp_sso_url` | VARCHAR(512) | no |  |  |
| `idp_cert` | TEXT | no |  |  |
| `created_at` | DATETIME | no |  | `_utcnow()` |

- Unique `uq_saml_config_org_id` on (org_id)

### `scim_group_members`

Model `ScimGroupMember` at `core/scim_models.py:23`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `group_id` | VARCHAR(36) | no | PK |  |
| `user_id` | VARCHAR(36) | no | PK, indexed |  |
| `org_id` | VARCHAR(50) | no | indexed |  |

- Index `ix_scim_group_members_org_id` on (org_id)
- Index `ix_scim_group_members_user_id` on (user_id)

### `scim_groups`

Model `ScimGroup` at `core/scim_models.py:13`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `org_id` | VARCHAR(50) | no | indexed |  |
| `display_name` | VARCHAR(255) | no |  |  |
| `created_at` | FLOAT | no |  | `time()` |

- Index `ix_scim_groups_org_id` on (org_id)
- Unique `uq_scim_group_org_name` on (org_id, display_name)

### `snapshots`

Model `Snapshot` at `core/models.py:134`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `run_id` | VARCHAR(36) | no | FK runs.id, indexed |  |
| `file_path` | TEXT | yes |  |  |
| `content` | TEXT | yes |  |  |
| `created_at` | FLOAT | yes |  |  |

- Index `ix_snapshots_run_id` on (run_id)

### `token_budget_records`

Model `TokenBudgetRecord` at `core/models.py:324`. Per-org monthly token usage - replaces per-process SQLite file.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `org_id` | VARCHAR(50) | no | indexed |  |
| `month` | VARCHAR(7) | no |  |  |
| `input_tokens` | INTEGER | no |  | `0` |
| `output_tokens` | INTEGER | no |  | `0` |
| `runs` | INTEGER | no |  | `0` |
| `cache_hits` | INTEGER | no |  | `0` |
| `cache_misses` | INTEGER | no |  | `0` |
| `estimated_cost_usd` | FLOAT | no |  | `0.0` |
| `updated_at` | FLOAT | no |  | `time()` |

- Index `ix_token_budget_records_org_id` on (org_id)
- Unique `uq_token_budget_org_month` on (org_id, month)

### `user_learning_patterns`

Model `UserLearningPattern` at `core/models.py:397`. Per-user isolated learning patterns. Every query MUST filter by org_id AND user_id.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `org_id` | VARCHAR(50) | no | FK organisations.id ondelete=CASCADE, indexed |  |
| `user_id` | VARCHAR(36) | no | FK users.id ondelete=CASCADE, indexed |  |
| `pattern_type` | VARCHAR(64) | no |  |  |
| `pattern_key` | VARCHAR(256) | no |  |  |
| `pattern_value` | JSON | no |  | `dict()` |
| `confidence` | FLOAT | no |  | `0.5` |
| `occurrence_count` | INTEGER | no |  | `1` |
| `source_run_ids` | TEXT | yes |  |  |
| `last_updated_at` | DATETIME | no |  | `_utcnow()` |
| `created_at` | DATETIME | no |  | `_utcnow()` |

- Index `ix_user_learning_patterns_org_id` on (org_id)
- Index `ix_user_learning_patterns_user_id` on (user_id)
- Unique `uq_learning_pattern_key` on (org_id, user_id, pattern_type, pattern_key)

### `users`

Model `User` at `core/models.py:52`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `org_id` | VARCHAR(50) | no | FK organisations.id |  |
| `email` | VARCHAR(255) | no | unique |  |
| `password_hash` | VARCHAR(255) | no |  |  |
| `role` | VARCHAR(50) | no |  | `'member'` |
| `is_active` | BOOLEAN | no |  | `True` |
| `user_preferences` | TEXT | yes |  |  |
| `consent_at` | DATETIME | yes |  |  |
| `deleted_at` | DATETIME | yes |  |  |
| `created_at` | DATETIME | no |  | `_utcnow()` |
| `mfa_secret` | TEXT (EncryptedText) | yes |  |  |
| `mfa_enabled` | BOOLEAN | no |  | `False` |
| `email_verified` | BOOLEAN | no |  | `False` |
| `must_change_password` | BOOLEAN | no |  | `False` |
| `updated_at` | DATETIME | yes |  |  |

- Unique `unnamed` on (email)

### `webhooks`

Model `Webhook` at `core/models.py:194`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `org_id` | VARCHAR(50) | no | indexed |  |
| `url` | VARCHAR(512) | no |  |  |
| `events` | JSON | yes |  |  |
| `secret` | VARCHAR(255) | yes |  |  |
| `secret_hash` | VARCHAR(255) | yes |  |  |
| `is_active` | BOOLEAN | no |  | `True` |
| `created_at` | DATETIME | no |  | `_utcnow()` |
| `last_triggered_at` | DATETIME | yes |  |  |

- Index `ix_webhooks_org_id` on (org_id)

### `workspaces`

Model `Workspace` at `core/models.py:207`.

| Column | Type | Nullable | Key / FK | Default |
|---|---|---|---|---|
| `id` | VARCHAR(36) | no | PK | generated in Python |
| `org_id` | VARCHAR(50) | no | indexed |  |
| `name` | VARCHAR(255) | no |  |  |
| `description` | TEXT | yes |  |  |
| `preferences` | JSON | yes |  |  |
| `created_by` | VARCHAR(36) | no |  |  |
| `created_at` | DATETIME | no |  | `_utcnow()` |
| `is_shared` | BOOLEAN | no |  | `False` |

- Index `ix_workspaces_org_id` on (org_id)


## Relationships

```
organisations
  |- users, api_keys, runs, global_patterns, user_learning_patterns, codebase_profiles
runs
  |- events, snapshots, phase_completions, run_specs, build_feedback, pipeline_events, llm_traces,
     questionnaire_sessions, learning_clarifications_pending
users
  |- user_learning_patterns
```

Everything else is linked by a string `org_id` or `run_id` without a foreign key.
