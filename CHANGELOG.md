# Changelog

All notable changes to AetherOS are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.1.0] — 2026-05-24

Initial public release of AetherOS — the autonomous, multi-tenant AI software factory.

### Added
- 20-phase pipeline: intake → architecture → scaffolding → backend → frontend → review → testing → self-healing → CI/CD → observability → docs → deployment → monitoring → error tracking → analytics → alerting → feature flags → A/B testing → app memory → client portal
- Multi-tenant platform with `org_id`-scoped isolation enforced at middleware level
- Anthropic Claude Sonnet 4.6 as primary LLM; Google Gemini 2.5 Flash as secondary; Ollama as local fallback
- Amazon Bedrock integration with cross-region inference profile support
- React 18 / TypeScript / Vite / Tailwind CSS dashboard with 20+ navigation tabs
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

[Unreleased]: https://github.com/AetherOS/aether_os/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/AetherOS/aether_os/releases/tag/v0.1.0
