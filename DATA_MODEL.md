# AetherOS Data Model

This document describes the PostgreSQL database schema used by AetherOS. All tables are managed via Alembic migrations. The primary model file is `core/models.py`.

---

## Core Tables

### `organisations`

The top-level multi-tenant unit. Every resource in AetherOS is scoped to an organisation.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) PK | UUID |
| `name` | VARCHAR(255) NOT NULL | Organisation display name |
| `slug` | VARCHAR(255) UNIQUE NOT NULL | URL-safe identifier |
| `plan` | VARCHAR(50) DEFAULT 'trial' | Subscription plan: `trial`, `pro`, `enterprise` |
| `created_at` | DATETIME | Creation timestamp |
| `trial_runs_used` | INTEGER DEFAULT 0 | Runs consumed during trial |
| `trial_runs_limit` | INTEGER DEFAULT 3 | Maximum trial runs allowed |
| `storage_used_mb` | FLOAT DEFAULT 0.0 | Cumulative artifact storage used |
| `autonomous_mode` | BOOLEAN DEFAULT false | Enables fully autonomous pipeline (no human gates) |
| `data_region` | VARCHAR(20) DEFAULT 'global' | Data residency region |
| `scim_token` | VARCHAR(128) nullable | Bearer token for IdP SCIM provisioning |
| `stripe_customer_id` | VARCHAR(64) nullable | Stripe Customer ID for billing/invoice lookup |

**Relationships**: has many `users`, `api_keys`, `runs`.

---

### `users`

Individual user accounts. Each user belongs to exactly one organisation.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) PK | UUID |
| `org_id` | VARCHAR(36) FK → organisations.id NOT NULL | Owning organisation |
| `email` | VARCHAR(255) UNIQUE NOT NULL | Login email |
| `password_hash` | VARCHAR(255) NOT NULL | bcrypt hash |
| `role` | VARCHAR(50) DEFAULT 'member' | `owner`, `admin`, `member`, `viewer` |
| `is_active` | BOOLEAN DEFAULT true | Account active status |
| `user_preferences` | TEXT nullable | JSON blob of UI preferences |
| `consent_at` | DATETIME nullable | Timestamp of data processing consent |
| `deleted_at` | DATETIME nullable | Soft-delete timestamp |
| `created_at` | DATETIME | Creation timestamp |
| `mfa_secret` | VARCHAR(64) nullable | TOTP secret (encrypted at rest) |
| `mfa_enabled` | BOOLEAN DEFAULT false | Whether TOTP MFA is active |

---

### `api_keys`

API keys for programmatic access. Keys are hashed before storage.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) PK | UUID |
| `org_id` | VARCHAR(36) FK → organisations.id | Owning organisation |
| `key_hash` | VARCHAR(255) NOT NULL | SHA-256 hash of the raw key |
| `name` | VARCHAR(255) NOT NULL | Human-readable label |
| `last_used_at` | FLOAT nullable | Unix timestamp of last use |
| `is_active` | BOOLEAN DEFAULT true | Whether the key is usable |
| `created_at` | DATETIME | Creation timestamp |

---

## Pipeline Tables

### `runs`

A pipeline run represents one end-to-end execution of the 20-phase factory pipeline.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) PK | UUID (run_id) |
| `org_id` | VARCHAR(36) FK → organisations.id nullable | Owning organisation |
| `user_id` | VARCHAR(36) nullable | Initiating user |
| `command` | TEXT nullable | Original command/input |
| `raw_input` | TEXT nullable | Raw requirement text |
| `requirement` | TEXT nullable | Parsed/structured requirement |
| `project_name` | VARCHAR(512) nullable | Project display name |
| `domain` | VARCHAR(100) DEFAULT 'general' | Pipeline domain (saas, fintech, etc.) |
| `client_id` | VARCHAR(255) nullable | Client identifier for portal |
| `status` | VARCHAR(50) nullable | `queued`, `running`, `completed`, `failed`, `cancelled`, `paused` |
| `current_phase` | VARCHAR(100) nullable | Active phase name |
| `started_at` | FLOAT nullable | Unix timestamp of run start |
| `finished_at` | FLOAT nullable | Unix timestamp of run completion |
| `live_url` | TEXT nullable | URL of the deployed generated app |
| `cost` | FLOAT DEFAULT 0.0 | Total LLM cost in USD |
| `run_version` | INTEGER DEFAULT 1 | Version counter for rerun tracking |
| `phases` | JSON nullable | Per-phase status and gate results |
| `council_preflight` | JSON nullable | Pre-run council check result |
| `council_delivery` | JSON nullable | Post-run council check result |
| `message` | TEXT nullable | Status or error message |
| `parent_run_id` | VARCHAR(36) nullable | Parent run for branch/rerun |
| `branch_phase` | VARCHAR(100) nullable | Phase at which a branch was created |
| `parallel_run_group_id` | VARCHAR(36) nullable | Groups parallel run variants |
| `self_test_report` | TEXT nullable | JSON self-test results |
| `quality_score` | INTEGER nullable | Overall quality score (0–100) |

**Relationships**: has many `events`, `snapshots`, `phase_completions`.

---

### `events`

Per-phase agent events emitted during a pipeline run. Streamed to the client via SSE.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) PK | UUID |
| `run_id` | VARCHAR(36) FK → runs.id NOT NULL | Parent run |
| `agent` | VARCHAR(255) nullable | Agent name that emitted the event |
| `action` | VARCHAR(255) nullable | Event type (e.g., `phase_start`, `gate_passed`) |
| `detail` | TEXT nullable | Event payload/message |
| `timestamp` | FLOAT nullable | Unix timestamp |

---

### `phase_completions`

Completion record for each phase within a run. Used for resuming and rerun-from-phase.

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | VARCHAR(36) FK → runs.id PK | Parent run |
| `phase_name` | VARCHAR(255) PK | Phase identifier |
| `status` | VARCHAR(50) nullable | `completed`, `failed`, `skipped` |
| `duration_s` | FLOAT nullable | Phase wall-clock duration in seconds |
| `updated_at` | FLOAT nullable | Unix timestamp of last update |

---

### `snapshots`

Point-in-time file snapshots for the Monaco editor diff view and rollback.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) PK | UUID |
| `run_id` | VARCHAR(36) FK → runs.id NOT NULL | Parent run |
| `file_path` | TEXT nullable | Relative path within the project |
| `content` | TEXT nullable | File content at snapshot time |
| `created_at` | FLOAT nullable | Unix timestamp |

---

### `run_specs`

Frontend and backend spec JSON attached to a run from the Builder UI tabs.

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | VARCHAR(36) FK → runs.id PK | Parent run |
| `spec_type` | VARCHAR(32) PK | `frontend` or `backend` |
| `spec` | JSON NOT NULL | Spec payload |
| `created_at` | DATETIME | |
| `updated_at` | DATETIME | |

---

### `decisions`

Human-in-the-loop decision tickets. The pipeline pauses until a decision is resolved.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) PK | UUID |
| `run_id` | VARCHAR(36) NOT NULL | Parent run |
| `org_id` | VARCHAR(36) NOT NULL | Owning organisation |
| `decision_type` | VARCHAR(100) NOT NULL | Category of decision |
| `title` | VARCHAR(255) NOT NULL | Decision summary |
| `what` | TEXT NOT NULL | What is being decided |
| `why` | TEXT NOT NULL | Why human input is needed |
| `alternatives` | JSON nullable | Option list |
| `impact` | TEXT nullable | Consequence description |
| `phase` | VARCHAR(100) nullable | Phase that raised the decision |
| `status` | VARCHAR(50) DEFAULT 'pending' | `pending`, `approved`, `denied`, `timed_out` |
| `human_choice` | VARCHAR(100) nullable | Selected option |
| `timeout_seconds` | INTEGER DEFAULT 300 | Auto-deny timeout |
| `created_at` | DATETIME | |
| `decided_at` | DATETIME nullable | |

---

### `phase_configs`

Per-org phase configuration overrides.

| Column | Type | Description |
|--------|------|-------------|
| `org_id` | VARCHAR(36) PK | Owning organisation |
| `phase_name` | VARCHAR(255) PK | Phase identifier |
| `enabled` | INTEGER DEFAULT 1 | 1 = enabled, 0 = disabled |
| `priority` | VARCHAR(50) DEFAULT 'normal' | Execution priority |
| `updated_at` | FLOAT nullable | Last update timestamp |

---

## Billing and Usage Tables

### `llm_call_records`

Individual LLM call records for per-run, per-phase cost tracking.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) PK | UUID |
| `org_id` | VARCHAR(36) nullable | Owning organisation |
| `project_id` | VARCHAR(255) NOT NULL | Run/project identifier |
| `phase` | VARCHAR(100) NOT NULL | Phase that made the call |
| `model` | VARCHAR(100) NOT NULL | Model name used |
| `input_tokens` | INTEGER DEFAULT 0 | |
| `output_tokens` | INTEGER DEFAULT 0 | |
| `cost_usd` | FLOAT DEFAULT 0.0 | Estimated cost |
| `created_at` | FLOAT | Unix timestamp |

---

### `token_budget_records`

Monthly per-org token usage aggregates.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) PK | UUID |
| `org_id` | VARCHAR(36) NOT NULL | Owning organisation |
| `month` | VARCHAR(7) NOT NULL | `YYYY-MM` format |
| `input_tokens` | INTEGER DEFAULT 0 | |
| `output_tokens` | INTEGER DEFAULT 0 | |
| `runs` | INTEGER DEFAULT 0 | Completed runs in month |
| `cache_hits` | INTEGER DEFAULT 0 | LLM cache hits |
| `cache_misses` | INTEGER DEFAULT 0 | LLM cache misses |
| `estimated_cost_usd` | FLOAT DEFAULT 0.0 | |
| `updated_at` | FLOAT | Unix timestamp |

---

### `llm_cache_entries`

Shared LLM response cache (SHA-256 keyed by prompt hash + task type).

| Column | Type | Description |
|--------|------|-------------|
| `cache_key` | VARCHAR(64) PK | SHA-256 hex of prompt+model |
| `task_type` | VARCHAR(64) NOT NULL | Task category |
| `response` | TEXT NOT NULL | Cached LLM response |
| `prompt_tokens` | INTEGER DEFAULT 0 | |
| `hit_count` | INTEGER DEFAULT 0 | Cache hit counter |
| `created_at` | FLOAT | |
| `last_hit_at` | FLOAT | |

---

## Auth and Identity Tables

### `audit_log`

Append-only audit ledger. Rows are never updated or deleted.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) PK | UUID |
| `org_id` | VARCHAR(36) NOT NULL | Owning organisation |
| `user_id` | VARCHAR(36) NOT NULL | Acting user |
| `action` | VARCHAR(255) NOT NULL | Action performed |
| `resource_type` | VARCHAR(100) NOT NULL | Resource category |
| `resource_id` | VARCHAR(36) NOT NULL | Resource identifier |
| `log_metadata` | TEXT nullable | JSON blob of additional context |
| `ip_address` | VARCHAR(45) nullable | Client IP (supports IPv6) |
| `created_at` | FLOAT | Unix timestamp |

---

### `saml_configs`

SAML IdP configuration per organisation.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) PK | UUID |
| `org_id` | VARCHAR(36) NOT NULL | Owning organisation |
| `idp_entity_id` | VARCHAR(512) NOT NULL | IdP entity ID URL |
| `idp_sso_url` | VARCHAR(512) NOT NULL | IdP SSO endpoint |
| `idp_cert` | TEXT NOT NULL | IdP signing certificate (PEM) |
| `created_at` | DATETIME | |

---

### `webhooks`

Outbound webhook registrations.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) PK | UUID |
| `org_id` | VARCHAR(36) NOT NULL | Owning organisation |
| `url` | VARCHAR(512) NOT NULL | Delivery endpoint |
| `events` | JSON nullable | List of subscribed event types |
| `secret` | VARCHAR(255) NOT NULL | HMAC-SHA-256 signing secret |
| `is_active` | BOOLEAN DEFAULT true | |
| `created_at` | DATETIME | |
| `last_triggered_at` | DATETIME nullable | |

---

## Intelligence and Learning Tables

### `global_patterns`

Cross-org aggregated pipeline patterns (anonymised). Used by the Improvement Loop engine.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) PK | UUID |
| `domain` | VARCHAR(255) NOT NULL | Pipeline domain |
| `pattern_name` | VARCHAR(255) NOT NULL | Pattern label |
| `pattern_type` | VARCHAR(100) NOT NULL | Type category |
| `success_rate` | FLOAT DEFAULT 0.0 | |
| `usage_count` | INTEGER DEFAULT 0 | |
| `avg_quality_score` | FLOAT DEFAULT 0.0 | |
| `last_updated` | DATETIME | |

---

### `user_learning_patterns`

Per-user learning patterns. Every query must filter by both `org_id` and `user_id`.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) PK | UUID |
| `org_id` | VARCHAR(36) FK → organisations.id CASCADE | |
| `user_id` | VARCHAR(36) FK → users.id CASCADE | |
| `pattern_type` | VARCHAR(64) NOT NULL | |
| `pattern_key` | VARCHAR(256) NOT NULL | |
| `pattern_value` | JSON NOT NULL | |
| `confidence` | FLOAT DEFAULT 0.5 | |
| `occurrence_count` | INTEGER DEFAULT 1 | |
| `source_run_ids` | TEXT nullable | JSON array of contributing run IDs |
| `last_updated_at` | DATETIME | |
| `created_at` | DATETIME | |

---

## Plugin and Marketplace Tables

### `installed_plugins`

Plugins installed per organisation.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) PK | UUID |
| `org_id` | VARCHAR(36) NOT NULL | |
| `plugin_id` | VARCHAR(100) NOT NULL | Plugin catalogue identifier |
| `config_json` | TEXT nullable | Encrypted plugin config JSON |
| `installed_at` | FLOAT | |
| `last_tested_at` | FLOAT nullable | |
| `test_status` | VARCHAR(20) nullable | `ok` or `fail` |

---

### `marketplace_profiles`

Reusable pipeline profiles published to the marketplace.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) PK | UUID |
| `org_id` | VARCHAR(36) NOT NULL | Publishing organisation |
| `name` | VARCHAR(255) NOT NULL | |
| `base_domain` | VARCHAR(255) NOT NULL | Target domain |
| `description` | TEXT nullable | |
| `price_usd` | FLOAT DEFAULT 0.0 | |
| `profile_yaml` | TEXT NOT NULL | Pipeline configuration YAML |
| `is_published` | BOOLEAN DEFAULT false | |
| `usage_count` | INTEGER DEFAULT 0 | |
| `created_at` | DATETIME | |

---

## Workspace and Notification Tables

### `workspaces`

Named workspaces for organising runs within an organisation.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) PK | UUID |
| `org_id` | VARCHAR(36) NOT NULL | |
| `name` | VARCHAR(255) NOT NULL | |
| `description` | TEXT nullable | |
| `preferences` | JSON nullable | |
| `created_by` | VARCHAR(36) NOT NULL | User ID of creator |
| `created_at` | DATETIME | |
| `is_shared` | BOOLEAN DEFAULT false | Visible to all org members |

---

### `notifications`

In-app notifications. `user_id = NULL` means org-wide broadcast.

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(36) PK | UUID |
| `org_id` | VARCHAR(36) NOT NULL | |
| `user_id` | VARCHAR(36) nullable | Target user (null = org-wide) |
| `type` | VARCHAR(64) NOT NULL | Notification category |
| `title` | VARCHAR(255) NOT NULL | |
| `message` | TEXT nullable | |
| `link` | VARCHAR(512) nullable | |
| `is_read` | BOOLEAN DEFAULT false | |
| `created_at` | FLOAT | Unix timestamp |

---

## Key Relationships Summary

```
organisations
  ├── users (1:N)
  ├── api_keys (1:N)
  └── runs (1:N)
        ├── events (1:N)
        ├── snapshots (1:N)
        ├── phase_completions (1:N)
        └── run_specs (1:N)

users
  └── user_learning_patterns (1:N, also scoped by org_id)

runs
  └── decisions (via run_id, not FK enforced)
```

All tables with `org_id` are partitioned logically by organisation. There are no cross-org queries in normal operation.
