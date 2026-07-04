# Changelog

All notable changes to AetherOS are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- **Pipeline checkpoint/resume**: Failed runs resume from last completed phase via `checkpoint_data` JSONB column on `runs` table; eliminates full restart on transient LLM failures
- **Zero-trust identity module**: `core/identity/zero_trust.py` — HMAC-SHA256 signed tickets for agent-to-resource access authorisation
- **Audit log hash-chaining**: `prev_hash` column on `audit_log` table; SOC 2 tamper evidence via SHA-256 chain
- **Codebase import**: Settings page allows importing an existing GitHub repository; stack detection wires into pipeline as pre-populated scaffold
- **Audit log CSV export**: Admin endpoint `GET /admin/audit/export.csv` for compliance downloads
- **p02b domain IR phase**: Normalised intermediate representation emitted between architecture and scaffolding phases; consumed by all downstream LLM prompts to avoid redundant domain re-detection

### Fixed
- Council quality gate default changed from `True` to `False` — malformed LLM responses no longer silently pass gates
- SSE stream now polls `_local_history` buffer when Redis is unavailable (was abandoning the stream entirely)
- `asyncio.Lock()` lazy-init: `AuditLogger` defers lock creation to first use, fixing Python 3.9 event-loop-at-import error
- Prometheus isolated `CollectorRegistry` in generated apps prevents `ValueError: Duplicated timeseries` on sequential pipeline runs
- Stripe subscription cancellation now calls `stripe.Subscription.cancel()` before downgrading plan in DB (was only updating DB)
- `stripe_customer_id` added to `Organisation` model and migration (was missing from schema)
- Test suite singleton contamination fixed: `DecisionLedger._instance = None` in finally block; RS256 env vars cleared before JWT HS256 tests

### Migrations (apply in order)
```bash
alembic upgrade add_stripe_customer_id
alembic upgrade add_codebase_profiles
alembic upgrade add_audit_log_prev_hash
alembic upgrade add_pipeline_run_checkpoint
```

---

## [1.0.0] — 2026-06-01

First stable release. All enterprise features complete, load-tested, and Playwright-verified.

### Added
- **Project Designer**: Unified New Project wizard with HSL colour picker, tech-stack configurator, and designer_spec pipeline wiring (replaces legacy two-step wizard)
- **Full Development Environment (FDE)**: Monaco editor in-browser, env-var panel, run-app process manager, VS Code extension one-click open
- **SCIM v2 provisioning UI**: Settings page SCIM section with token management and Okta/Azure AD setup guide
- **Marketplace CRUD**: Publish, browse, install, and manage reusable pipeline profiles
- **Council preflight/delivery gates**: Truth Engine, Conflict Resolver, Tradeoff Engine, and Improvement Loop wired into pipeline gate evaluation
- **Portal ZIP + provenance**: Client portal delivers signed artifact ZIP with build provenance JSON
- **Quality metrics trend**: 5-point rolling quality score chart on project view
- **Workspace management**: CRUD for logical workspaces within an organisation
- **Memory knowledge graph**: D3.js interactive graph view of ChromaDB entity relationships
- **4-router extraction**: Factory ops, factory runs, guardian, and account routers extracted from monolithic api.py
- **GrowthBook feature flags**: Wired into p12a phase with flag definitions and gradual-rollout config
- **Bedrock cross-region inference profile support**: Heavy tasks via Sonnet, light tasks via Haiku
- **Air-gapped deployment mode**: `OFFLINE_MODE=true` + Ollama for fully local operation
- **External monitor bridge**: Optional integration with external predictive monitoring

### Fixed
- p07b self-healing gate now correctly sets `passed=False` on error (quality gate restored)
- p08/p09 double-execution eliminated (8 phases no longer run twice on large pipelines)
- p10 bad imports from retired phase modules corrected
- p06 security LLM call fixed (wrong import + `task=` kwarg)
- Council `_ERROR_RESULT` now sets `passed=False` (was silently passing on exception)
- Billing stats endpoint returning incorrect aggregate totals
- Portal requirements not propagating to p14 client portal phase
- Duplicate pipeline run creation on concurrent POST requests
- SAML assertion route changed HEAD→GET
- SSE v2 token moved from URL query param to header (SEC fix)
- Redis password enforcement and PostgreSQL port no longer host-exposed
- asyncio.ensure_future loop= removed (Python 3.10+ compatibility)
- All `datetime.utcnow()` replaced with timezone-aware `datetime.now(timezone.utc)`
- Alembic heads merged and UNIQUE constraint on org/provider added for `org_api_keys`

### Security
- Field-level Fernet encryption applied to `mfa_secret`, `org_api_keys.api_key`, and LLM provider keys
- Zero-trust execution secret (`AETHER_ONE_ZT_SECRET`) raises RuntimeError if unset
- CORS origins never wildcard — reads from `CORS_ORIGINS` env var exclusively
- Rate limiting: Redis sliding-window on login (5/15 min), registration (5/hr), factory-start (10/min)
- Prompt injection guard: 10 jailbreak + 5 shell injection patterns blocked at intake
- Password checked against HIBP (Have I Been Pwned) on registration
- `METRICS_API_KEY` now enforced on `/metrics` endpoint when set
- systemd service demoted from root to `aetheros` user with ProtectSystem=strict

### Performance
- Load test: p95 = 240ms, 0% error rate at 50 concurrent users (Locust)
- SQLite WAL mode + 22 explicit indexes on all high-traffic query patterns
- PostgreSQL connection pool tuned: pool_size=3, max_overflow=7 per worker (safe under 100 max_connections default)

---

## [0.1.0] — 2026-05-24

Initial public release of AetherOS — the autonomous, multi-tenant AI software factory.

### Added
- 21-phase pipeline: intake → architecture → domain IR → scaffolding → backend → frontend → review → testing → self-healing → CI/CD → observability → docs → deployment → monitoring → error tracking → analytics → alerting → feature flags → A/B testing → app memory → client portal
- Multi-tenant platform with `org_id`-scoped isolation enforced at middleware level
- Anthropic Claude Sonnet 4.6 as primary LLM; Google Gemini 2.5 Flash as secondary; Ollama as local fallback
- Amazon Bedrock integration with cross-region inference profile support
- React 18 / TypeScript / Vite / Tailwind CSS dashboard with 21+ navigation tabs
- Full Development Environment (FDE): Monaco editor in-browser, env-var management, run-app process manager
- VS Code extension with live pipeline status and one-click project open
- CLI (`aether` command) built with Typer + Rich for terminal-based pipeline management
- JWT authentication with refresh token rotation; TOTP MFA; SAML SSO; OAuth2 social login
- SCIM v2 automated user provisioning for enterprise IdPs
- Razorpay billing integration with order creation, payment verification, and webhook processing
- Append-only audit ledger per organisation
- Compliance engines: GDPR, HIPAA, PCI-DSS, SOC2 domain-aware guardrails
- Intelligence engines: Arch Governor, Truth Engine, Conflict Resolver, Tradeoff Engine, Improvement Loop, Maintenance Engine
- D3 memory knowledge graph with ChromaDB vector store and mem0 integration
- Marketplace for reusable pipeline profiles
- Webhook delivery system with HMAC-SHA-256 signatures
- Prometheus metrics, structlog structured logging, OTEL instrumentation
- Bandit + Semgrep security scanning in CI pipeline
- Load tested at p95 = 240 ms, 0% error rate, 50 concurrent users
- PostgreSQL (asyncpg + SQLAlchemy async 2.0 + Alembic) as primary datastore
- Redis message bus (RPUSH/BLPOP primary; asyncio.Queue fallback for single-process mode)
- Systemd service unit, nginx reverse proxy config, certbot TLS, logrotate, fail2ban configs
- Cache-Control no-cache on index.html to prevent stale bundle errors on redeploy

### Fixed
- Billing stats endpoint returning incorrect aggregate totals
- Portal requirements not propagating to p14 client portal phase
- Duplicate pipeline run creation on concurrent POST requests
- p06 security phase gate incorrectly passing partial results
- "Inconclusive" label appearing on conclusive gate results
- Members heading rendering incorrectly in admin panel
- Page auto-scrolling on agent event stream updates
- Artifact schema migration compatibility with existing runs
- Phase timeout handling for long-running LLM tasks
- p07a-d testing agent selector returning wrong agent class
- spec_cache key collision across concurrent runs
- p01/p04a/p04b LLM codegen failing on structured output schema mismatch
- p11a dashboard provisioning not generating Grafana JSON
- Council timeout not propagating to phase gate result
- BEDROCK_MODEL_HEAVY/LIGHT env var name mismatch

### Security
- Zero-trust execution sandbox for generated-code subprocess invocation
- Bare-except handlers replaced with specific exception catches across critical paths
- LangSmith telemetry gated behind explicit user consent
- ARIA/WCAG 2.1 AA compliance applied to all dashboard components
- Rate limiting hardened on all public auth endpoints

[Unreleased]: https://github.com/Vk-AtOS/aether_os/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Vk-AtOS/aether_os/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/Vk-AtOS/aether_os/releases/tag/v0.1.0
