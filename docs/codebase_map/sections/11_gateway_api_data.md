# 11 — Gateway, API Management Plane & Data Model

Scope: `gateway/**` (68 .py files, 14,236 LOC), `alembic/` (56 files, 2,866 LOC), `alembic.ini`, cross-checked against `API_REFERENCE.md` (989 lines) and `DATA_MODEL.md` (441 lines). Git HEAD 052a101. Every in-scope file was read in full; ORM models were cross-checked against `core/models.py` and `core/guardian/models.py`.

Auth legend in tables: **N** = none (public) · **U** = any authenticated principal via `get_current_user` (user JWT or `aesk_` API key) · **A** = U plus role owner|admin (some also accept superadmin) · **O** = owner only · **S** = superadmin only · **J** = raw JWT decode only (skips blacklist, is_active, email_verified and mfa_pending checks) · **P** = portal token or any JWT · **Q** = questionnaire URL token · **T** = SCIM bearer · **X** = one-time SSE token · **K** = `X-Metrics-Key` · **W** = provider HMAC signature · **I** = no ownership check (IDOR).

---

## 1. Summary

- **Single FastAPI app.** It is built by `create_app()` in `gateway/api.py:93`. 55 routers are loaded from a table (`api.py:228-288`): 28 are `required=True` (startup aborts if one fails to import) and 27 are optional (a failure only logs a warning). All 53 router files in `gateway/routers/` are mounted; the 3 helper modules export no router. Two more routers come from outside the gateway: `phases.p08_cicd.webhook` and `gateway.client_portal.routes`. The `mcp`, `saml`, `oauth` and `mfa` routers live in `gateway/*.py`.
- **About 282 live HTTP operations** (280 route decorators in `gateway/` plus 2 CI/CD routes; a few decorators are stacked aliases or dead SPA branches). `API_REFERENCE.md` documents about 75 of them, and about 25 of those do not exist (the whole `/v2/auth/*` and `/v2/factory/*` families).
- **Identity.** Access tokens are RS256 JWTs (1 h) plus refresh JWTs (30 d), with HS256 fallback and legacy-decode paths still in the code. A Redis jti blacklist fails closed. Other identity features: TOTP MFA as a second step, Google and GitHub OAuth, per-org SAML (python3-saml; Okta and others configured per org), SCIM 2.0 (static env token, a per-org bcrypt token, or a JWT fallback), SHA-256-hashed `aesk_` org API keys, and 4 org roles (owner, admin, member, viewer) plus an implicit `superadmin` that no API can grant.
- **Tenancy is enforced per handler**, not centrally: each handler is expected to filter on `org_id` itself. About 20 run-scoped endpoints skip that check (IDOR, §8).
- **Critical security findings (§8.1):**
  - Unauthenticated runtime feature-flag writes.
  - An unauthenticated CI webhook that queues repair jobs against any server path.
  - An unauthenticated `/_metrics_internal`.
  - Any member can replace the org SAML IdP config. Because the SAML callback looks users up by global email, this is a cross-tenant account takeover.
  - Free plan upgrades through `/billing/downgrade` and the Razorpay `plan` field.
  - A same-origin `/app-preview` proxy with `default-src *` serves untrusted generated code, while the dashboard keeps JWTs in `localStorage`.
  - Refresh tokens are accepted as access tokens.
- **The data model has 35 ORM tables** (33 in `core/models.py`, 2 guardian tables). The Alembic graph has a single head (`revision_pgvector_artifact_embedding`) and 8 merge nodes, but it **cannot be replayed on an empty database**: several revisions create the same tables or columns twice, and 4 ORM tables plus `guardian_events.org_id` are never created by any migration. The real schema source is `init_db()` (create_all), called at startup (`lifespan.py:131`).

---

## 2. Coverage table

Status tags: LIVE = mounted and used · HELPER = imported support module · DEAD = not imported anywhere, or unreachable · BIG = router over 400 lines (rule in CLAUDE.md) · RISK = contains a §8.1 finding.

| File | LOC | Purpose | Status |
|---|---|---|---|
| gateway/__init__.py | 1 | package marker | LIVE |
| gateway/api.py | 322 | app factory, middleware, router table, static mounts | LIVE |
| gateway/lifespan.py | 308 | startup and shutdown checks, crash recovery, seeding, background workers | LIVE |
| gateway/api_helpers.py | 206 | 14 Pydantic models (mostly dead re-exports) and 3 middleware classes | LIVE (models DEAD) |
| gateway/api_utils.py | 131 | Sentry init, CORS origins, golden-example seeder, `_json_safe` | LIVE |
| gateway/auth.py | 250 | JWT key loading and signing, bcrypt, API-key hashing | LIVE (`verify_token_dependency` DEAD) |
| gateway/dependencies.py | 134 | `get_current_user` (JWT or API key), `security_scheme` | LIVE |
| gateway/auth_mfa.py | 212 | TOTP setup, verify, disable, confirm | LIVE |
| gateway/auth_oauth.py | 313 | Google and GitHub OAuth2 | LIVE |
| gateway/auth_saml.py | 284 | SAML SP: metadata, login, ACS | LIVE, RISK |
| gateway/security.py | 42 | GitHub, GitLab and Jenkins HMAC/token verifiers | DEAD (never imported) |
| gateway/mcp_router.py | 137 | `/mcp/*` REST facade over legacy SQLite | LIVE, RISK (IDOR) |
| gateway/client_portal/__init__.py | 1 | marker | LIVE |
| gateway/client_portal/routes.py | 452 | `/portal/*` client delivery portal | LIVE, BIG, RISK |
| gateway/services/__init__.py | 0 | marker | — |
| gateway/services/admin_service.py | 165 | invite and reset-password logic, email | HELPER |
| gateway/routers/__init__.py | 0 | marker | — |
| routers/account_router.py | 203 | usage, storage, projects, GDPR export and delete, preferences | LIVE |
| routers/account_settings_router.py | 174 | org settings, org delete and restore, `/orgs/me/usage` | LIVE |
| routers/account_codebase_router.py | 279 | GitHub repo import into `codebase_profiles` | LIVE |
| routers/admin_router.py | 356 | user management, audit CSV, error registry | LIVE |
| routers/admin_platform_router.py | 278 | platform health, kill-all, prune, audit export, git deploy, file save | LIVE |
| routers/admin_quality_router.py | 330 | quality metrics, run costs, phase latency | LIVE |
| routers/agents_router.py | 71 | list and run registered agents | LIVE, RISK |
| routers/app_preview_router.py | 178 | `/app-preview/*` reverse proxy | LIVE, RISK |
| routers/auth_router.py | 279 | register, login, logout | LIVE |
| routers/auth_refresh_router.py | 112 | refresh | LIVE |
| routers/auth_keys_router.py | 221 | API keys, MFA status, my-orgs, switch-org | LIVE |
| routers/auth_password_router.py | 249 | verify-email, password reset and change | LIVE |
| routers/billing_router.py | 262 | Razorpay plans, order, verify, invoices, cancel, downgrade, webhook | LIVE, RISK |
| routers/billing_stripe_router.py | 258 | Stripe checkout, webhook, portal | LIVE |
| routers/compliance_router.py | 251 | audit logs, export and purge, compliance ZIP, org report | LIVE |
| routers/factory_analytics_router.py | 258 | quality trends, search, deployments | LIVE |
| routers/factory_intake_router.py | 306 | upload, fetch GitHub, import DB schema, fetch repo (SSH) | LIVE, RISK |
| routers/factory_ops_router.py | 109 | pipeline status and approve, templates | LIVE |
| routers/factory_run_background.py | 393 | background runner, spec preamble, compliance pre-check, disk enrichment | HELPER |
| routers/factory_run_cleanup.py | 84 | post-build hooks (quality score, GlobalPattern, learning) | HELPER |
| routers/factory_run_compliance_router.py | 218 | run compliance, decisions, portal | LIVE (IDOR) |
| routers/factory_run_files_router.py | 358 | file tree, read/write, env vars, snapshots, changelog | LIVE |
| routers/factory_run_streaming_router.py | 187 | SSE token and stream | LIVE |
| routers/factory_runs_router.py | 439 | run list, detail, quality, priority, rerun, branch, events | LIVE, BIG (pre-approved) |
| routers/factory_start_router.py | 391 | `/factory/start`, `/factory/estimate` | LIVE |
| routers/guardian_router.py | 219 | status, stats, events, scan | LIVE (status bug) |
| routers/guardian_snapshots_router.py | 172 | resolve, snapshots, restore, baseline | LIVE |
| routers/health_router.py | 97 | health, zero-trust health, landing page, favicon | LIVE |
| routers/intelligence_router.py | 301 | GlobalPattern CRUD and T9 intelligence engines | LIVE |
| routers/learning_router.py | 124 | learning context, clarifications, feedback, golden builds | LIVE |
| routers/legal_router.py | 126 | ToS, privacy policy, DPA | LIVE |
| routers/marketplace_router.py | 199 | marketplace profiles | LIVE |
| routers/memory_router.py | 101 | memory search and graph | LIVE |
| routers/metrics_router.py | 40 | `/metrics` (key-protected) | LIVE |
| routers/notifications_router.py | 77 | in-app notifications | LIVE |
| routers/plugins_router.py | 208 | `/v2/plugins` catalog, install, invoke | LIVE |
| routers/plugins_connectors_router.py | 262 | `/v2/plugins` skills, Salesforce, LDAP | LIVE, RISK (SSRF) |
| routers/questionnaire_router.py | 349 | public and agency questionnaires | LIVE |
| routers/questionnaire_helpers.py | 126 | resume signal, SendGrid, validation | HELPER (resume broken) |
| routers/run_app_router.py | 273 | run, stop and status of the generated app; preview credentials | LIVE (IDOR) |
| routers/run_decisions_router.py | 181 | pause, resume, cancel, kill, restart | LIVE |
| routers/run_deploy_router.py | 232 | deploy and stop, artifacts, ZIP | LIVE |
| routers/run_preview_router.py | 311 | push-github, traces, specs, chat | LIVE (IDOR) |
| routers/run_spec_router.py | 335 | decision gates, spec, council review | LIVE (IDOR) |
| routers/scim_router.py | 237 | SCIM v2 Users and Groups | LIVE |
| routers/settings_router.py | 301 | models, org LLM keys, LangSmith, provider test | LIVE |
| routers/settings_advanced_router.py | 297 | LLM, council and phase config, preferences, SSO, SCIM token | LIVE, RISK |
| routers/spa_router.py | 65 | `/dashboard` SPA with CSP nonce injection | LIVE |
| routers/system_router.py | 248 | system metrics, status, health, workloop | LIVE |
| routers/system_info_router.py | 213 | observability, SLA, costs, pricing, feature flags | LIVE, RISK |
| routers/webhooks_router.py | 134 | outbound webhook CRUD and test | LIVE |
| routers/workspaces_router.py | 140 | workspaces CRUD | LIVE |
| alembic.ini | 117 | `script_location=alembic`; URL placeholder (env.py overrides it) | LIVE |
| alembic/env.py | 72 | builds the URL from `core.db._build_db_url`, strips async drivers, `render_as_batch` | LIVE |
| alembic/versions/*.py (55 files) | 2,794 | 47 schema revisions and 8 merge revisions (see §6.3) | see §6 |

Not in scope but mounted from here: `phases/p08_cicd/webhook.py`, which provides `POST /ci/webhook` and `GET /ci/jobs/{id}`, both public (§8.1).

---

## 3. App bootstrap and middleware

### 3.1 Import-time setup (`api.py`)
- `api.py:20` puts `~/Desktop` on `sys.path` so that the `aether_os.*` package imports resolve.
- `api.py:51` loads `.env`.
- `api.py:56` sets up structured JSON logging.
- `api.py:69` initialises Sentry when `SENTRY_DSN` is set (`api_utils.py:21`).
- `api.py:72` defines `_background_tasks`, which holds strong references to background tasks. Routers reach it with a circular `from aether_os.gateway import api` (`factory_runs_router.py:38`, `run_decisions_router.py:43`).
- `api.py:322` builds the module-level `app = create_app()`.
- `/docs` and `/redoc` are disabled when `ENVIRONMENT=production` (`api.py:108`).

### 3.2 Lifespan (`lifespan.py:43-308`), in startup order
1. `reload_keys()` loads the JWT keys; startup exits with code 1 if none are found (`:56-61`). The comment says the HS256 fallback was removed, but `auth.py:89-95` still contains it.
2. Redis ping. When `REQUIRE_REDIS=true` or `ENVIRONMENT=production` and Redis is missing, startup exits with code 1 (`:64-83`).
3. `AETHER_FIELD_KEY` (Fernet key for LLM API keys and MFA secrets) is required in production; elsewhere only a warning is logged (`:86-104`).
4. Warns when `CORS_ORIGINS` is unset in production (`:107`).
5. `SELECT 1` against Postgres; exits with code 1 on failure (`:114-127`).
6. `init_db()` creates all tables and indexes. **This, not Alembic, is the effective schema authority** (`:131`).
7. `ensure_demo_user()` (`:137`).
8. `load_validators()` loads validators learned by the repair system (`:143`).
9. `init_langsmith()` (`:149`).
10. CI call-graph pre-build from `AETHER_REPO_ROOT` (`:155`).
11. **Crash recovery**: phase_completions and runs still marked `running` are set to `interrupted` (`:162-183`).
12. Background `_restore_run_app()`: re-registers or restarts the most recent generated-app process from `~/.aether_os/projects/*/run_app_state.json` or Redis, acting as a synthetic admin user `{"org_id":None,"role":"admin"}` (`:186-236`).
13. Deletes `%example.com%` rows from `webhooks` left over from seed data (`:241-253`).
14. `ensure_marketplace()` and `_seed_golden_examples_if_empty()` (`:257`, `:263`; `api_utils.py:67`).
15. Starts the SQS consumer, the WorkloopMonitor, and the Guardian watchdog task (`:269-285`).
16. Shutdown stops the consumer, the monitor and the watchdog, then closes the DB (`:290-306`).

### 3.3 Middleware stack
Starlette treats the last-registered middleware as the outermost. Registration order is `api.py:113 → 158`.

| Order (outer → inner) | Middleware | Where | Notes |
|---|---|---|---|
| 1 | `audit_log_middleware` | api.py:158 | For POST, PUT, PATCH and DELETE outside the docs, health and metrics paths and `*/stream`, it decodes the Bearer token and starts an `async_log_audit_event` task. It sees the **unstripped** path, so for `/api/...` calls `resource_type` is logged as "api" |
| 2 | Prometheus Instrumentator | api.py:145 | `instrument(app)` adds middleware and `expose()` adds `/_metrics_internal` **with no auth** |
| 3 | GZip (≥500 B) | api.py:139 | |
| 4 | CORS | api.py:131 | origins come from `CORS_ORIGINS`, defaulting to 5 localhost origins (`api_utils.py:46`); `allow_credentials=True`; methods `*`; headers limited to Content-Type, Authorization, X-Org-ID, Accept. `X-Portal-Token`, `X-Metrics-Key` and `Last-Event-ID` are not allowed cross-origin |
| 5 | HttpsRedirect | api_helpers.py:197 | issues a 301 when `FORCE_HTTPS=true` and `X-Forwarded-Proto=http` |
| 6 | SecurityHeaders | api_helpers.py:138 | per-request CSP nonce; `script-src 'self' 'nonce' 'strict-dynamic' 'unsafe-eval' cdn.jsdelivr`; `frame-ancestors 'none'`; X-Frame-Options DENY; HSTS in production only; static `X-RateLimit-*` headers that echo config, not live counts; **skipped for `/app-preview*`** |
| 7 | OrgIDLogging | api_helpers.py:107 | binds org_id and user_id to the structlog context, taken from `X-Org-ID` (trusted from the client) or the JWT |
| 8 | `strip_api_prefix` | api.py:113 | rewrites `/api/x` to `/x`. It is innermost, so the `/api/health` route alias (`health_router.py:31`) and the empty `api_router` (`api.py:220`) are unreachable |

Exception handlers: 422 handler with the body truncated to 200 characters (`api.py:203`); catch-all 500 with a generic message (`api.py:210`). Many handlers still return `str(exc)` in their own 500 or 400 responses.

Static mounts: `/js` from `public/js` (`api.py:308`) and `/dashboard` via StaticFiles (`api.py:317`). The StaticFiles mount is shadowed by the `spa_router` `/dashboard/{path}` routes, which are registered first.

---

## 4. Auth and identity

### 4.1 JWT (`auth.py`)
- **Key loading order** (`auth.py:43-103`): `AETHER_JWT_PRIVATE_KEY_B64`/`PUBLIC_KEY_B64`, then `AETHER_JWT_*_KEY_PATH`, then `AETHER_SECRET_KEY` (HS256, documented as CI only, but it is accepted in any environment).
- **Claims**: `sub` (email), `user_id`, `org_id`, `org_slug`, `role`, `plan`, `exp`, `iat`, `jti` (uuid4) (`auth.py:186-195`). The access token lifetime is 1 h.
- **Refresh token**: the same signer with `token_type:"refresh"` and a 30-day lifetime (`auth.py:178`).
- **Decode** (`auth.py:200-237`) uses the active algorithm. In RS256 mode it **also accepts HS256 tokens signed with `AETHER_SECRET_KEY`** as a "migration window". Anyone holding that secret can forge tokens.
- **`get_current_user`** (`dependencies.py:28-134`), JWT branch, in order:
  1. Rejects `mfa_pending` tokens.
  2. Loads User and Org from the DB on every request; requires `is_active`, no `deleted_at`, org not `is_deleted`, and `email_verified` (403 `email_not_verified`).
  3. While `must_change_password` is set, blocks every path except `/auth/change-password` and `/auth/logout`.
  4. Checks the Redis `jwt:blacklist:{jti}` key and **fails closed with 503** when Redis is down.
- **Gap:** `token_type` is never checked, so **a 30-day refresh token works as an access token** everywhere.
- **API-key branch** (`dependencies.py:106-129`): a key starting with `aesk_` is SHA-256 hashed and looked up in `api_keys` (active only). The resulting principal is `{"sub":"api_key","org_id","org_slug","plan","role":"api"}` with **no `user_id`**, so handlers that read `user["user_id"]` return 500. Examples: `billing_router.py:97`, `learning_router.py:41`, `workspaces_router.py:71`, `run_preview_router.py:273`. Keys have no scopes and no expiry.

### 4.2 Login, refresh and logout
- **Register** (`auth_router.py:60`): IP rate limit; `terms_accepted` and `dpa_accepted` required; HIBP-backed password check that fails open; plan forced to `trial` and role forced to `owner` (`extra="forbid"`). Stores a 24 h email-verify token in Redis, sends the email, writes an audit entry, and returns access and refresh tokens. Those tokens fail every protected endpoint with 403 until the email is verified.
- **Login** (`auth_router.py:172`): IP rate limit. Every attempt is recorded before the check, including successful ones. The client IP is read from `X-Real-IP` or `X-Forwarded-For` (spoofable unless nginx overwrites them). Password check is bcrypt in an executor; failures are audited. When MFA is enabled, it returns `{mfa_required, mfa_token}`, where `mfa_token` is a 1 h JWT carrying `mfa_pending:true` (the docstring says 5 min).
- **Refresh** (`auth_refresh_router.py:42`): requires `token_type=refresh`, checks the blacklist (**fails open** here), re-reads the user and requires `is_active`, then issues a new access and refresh pair. **The old refresh token is never revoked**, so a stolen refresh token can be replayed for 30 days.
- **Logout** (`auth_router.py:251`): blacklists only the jti of the presented access token. The refresh token stays valid.
- **Password reset and change** (`auth_password_router.py`): Redis tokens `pw_reset:` (1 h) and `email_verify:` (24 h); the reset request is IP rate-limited and does not reveal whether the email exists. Neither reset nor change revokes existing sessions.

### 4.3 MFA (`auth_mfa.py`)
- `setup` stores a pyotp secret, which the `EncryptedText` column encrypts at rest.
- `verify-setup` enables MFA. `disable` requires a valid TOTP code.
- `confirm` (public): 5 attempts per 5 min per IP, **fails closed** without Redis. Replay protection keeps used codes in `mfa_used:{uid}:{code}` for 90 s and **fails open** without Redis. On success it returns access and refresh tokens.
- `pyotp` is imported at module level, so a missing package makes the optional `mfa` router fail to mount, silently.

### 4.4 OAuth (`auth_oauth.py`)
- Google (`openid email profile`, requires `email_verified`) and GitHub (`user:email`, primary verified address).
- The CSRF `state` lives in an **in-process dict** (`:41`), so it breaks with more than one worker.
- Callbacks upsert by global email. A new email auto-creates an org (`plan=trial`) with the user as `owner`.
- The login JWT is returned as `?token=` in the redirect URL to `FRONTEND_URL/auth/callback` (`:87`). No refresh token is issued, MFA is bypassed, and `is_active` is not checked.

### 4.5 SAML (`auth_saml.py`)
- SP settings come from `SAML_SP_ENTITY_ID` and `SAML_SP_ACS_URL`. IdP settings come per org from `saml_configs` (written by `PUT /settings/sso`), falling back to `SAML_IDP_*` env vars. `strict=True`, `debug=False`. Okta and other IdPs are configured purely through this per-org data.
- `/login?org=slug` redirects to the IdP but **does not set RelayState**. `/callback` (public POST) resolves the org from the `org` query parameter inside RelayState, then the env fallback, and returns 400 otherwise (`:202-215`).
- After validation, the user is looked up **by email across all orgs** (`:249`), auto-provisioned when missing, and access and refresh tokens are put in the redirect query string. MFA, `is_active` and `email_verified` are all bypassed. Combined with §8.1-4, this enables cross-tenant takeover.

### 4.6 SCIM (`scim_router.py`)
- `_verify_scim_auth` (`:39-106`) tries, in order:
  1. The `SCIM_BEARER_TOKEN` env token, mapped to `SCIM_ORG_ID` with role admin.
  2. Per-org tokens: it loads **every org** that has a token and bcrypt-compares against each one, which is O(N) bcrypt work per request (a DoS lever). The legacy plaintext `scim_token` is still accepted.
  3. **Any decodable JWT**, without the blacklist, is_active or MFA checks.
- Users: list, get, create (role member, random password), PUT (only `active`, and `displayName`, which is wrongly written into `users.user_preferences` and overwrites the consent JSON), DELETE (soft delete). Groups returns the org as a single group. PATCH (which Okta uses) is not implemented.
- Token rotation: `POST /settings/scim/rotate` (owner only, stores a bcrypt hash, returns the token once).

### 4.7 RBAC
- Roles live in `users.role`: owner, admin, member, viewer, plus `superadmin` (checked in about 12 places, but no endpoint can assign it: invite and role-change only allow the 4 standard roles, `admin_router.py:95,115`), plus `api` for API keys.
- All checks are inline `if user.get("role") ...`. There is no shared decorator.
- **Admins can invite owners** (`admin_router.py:95`) and can reset any user's password, including an owner's (`admin_router.py:129`; the response returns the temp password when email fails). That is a path from admin to owner.
- Viewer is only enforced on file and env-var writes (`factory_run_files_router.py:175,253`).
- `superadmin`-only actions: git pull and restart (`admin_platform_router.py:197`), platform file write (`:255`), Guardian snapshots and restore and baseline, error-registry mark-fixed.

### 4.8 Other credential types
- SSE: `POST /factory/runs/{id}/sse-token` creates a 30 s single-use token in Redis (`sse_token_set`). It is not checked against run ownership, but the stream re-verifies the org (`factory_run_streaming_router.py:78`).
- Portal: a `.portal_token` file per project, sent as the `X-Portal-Token` header or `?portal_token`. Only the approve and feedback writes require it.
- Questionnaire: 32-byte URL token with a 7-day TTL. Tokens are written to INFO logs (`questionnaire_router.py:280`).
- Metrics: `X-Metrics-Key`, compared without constant time. When unset, an ephemeral key is generated **and logged at WARNING** (`metrics_router.py:21-24`), and each worker generates a different one.
- Webhooks out: a 32-byte secret is returned once and stored only as a bcrypt hash. Because only the hash is kept, HMAC signing of outbound deliveries cannot be done with the original secret (open question).
- Inbound payment webhooks: Razorpay HMAC on the body (`billing_router.py:236`) and Stripe `construct_event` (`billing_stripe_router.py:129`).

---

## 5. Endpoint inventory (grouped by domain)

Unless marked, every route is mounted at the root. `/api/*` paths are rewritten to `/*` by the strip middleware. `/v2` applies only to the plugins routers.

### 5.1 Auth and identity
| Method | Path | File:line | Auth | Purpose |
|---|---|---|---|---|
| POST | /auth/register | auth_router.py:60 | N (IP RL) | create org and owner, send verification email |
| POST | /auth/login | auth_router.py:172 | N (IP RL) | password login, or `mfa_token` when MFA is on |
| POST | /auth/logout | auth_router.py:251 | U | blacklist the access-token jti |
| POST | /auth/refresh | auth_refresh_router.py:42 | N (refresh JWT) | issue a new pair (old refresh not revoked) |
| GET | /auth/verify-email | auth_password_router.py:40 | N (token) | set `email_verified` |
| POST | /auth/password-reset-request | auth_password_router.py:79 | N (IP RL) | email a reset link |
| POST | /auth/password-reset-confirm | auth_password_router.py:158 | N (token) | set a new password |
| POST | /auth/change-password | auth_password_router.py:207 | U | rotate password, clear `must_change_password` |
| POST | /auth/api-keys | auth_keys_router.py:40 | U (any role) | create an org `aesk_` key |
| GET | /auth/api-keys | auth_keys_router.py:91 | U | list org keys |
| DELETE | /auth/api-keys/{key_id} | auth_keys_router.py:109 | U | revoke a key |
| GET | /auth/mfa/status | auth_keys_router.py:143 | U | MFA enabled flag |
| GET | /auth/my-orgs | auth_keys_router.py:154 | U | the single org |
| POST | /auth/switch-org | auth_keys_router.py:180 | U | reissue tokens (single-org only) |
| POST | /auth/mfa/setup | auth_mfa.py:95 | U | generate TOTP secret |
| POST | /auth/mfa/verify-setup | auth_mfa.py:115 | U | enable MFA |
| POST | /auth/mfa/disable | auth_mfa.py:138 | U | disable MFA |
| POST | /auth/mfa/confirm | auth_mfa.py:160 | N (mfa_token, IP RL) | second factor, returns tokens |
| GET | /auth/oauth/google | auth_oauth.py:157 | N | redirect to Google |
| GET | /auth/oauth/google/callback | auth_oauth.py:177 | N (state) | upsert user, JWT in redirect |
| GET | /auth/oauth/github | auth_oauth.py:234 | N | redirect to GitHub |
| GET | /auth/oauth/github/callback | auth_oauth.py:251 | N (state) | upsert user, JWT in redirect |
| GET | /auth/saml/metadata | auth_saml.py:131 | N | SP metadata XML |
| GET | /auth/saml/login | auth_saml.py:155 | N | redirect to the org's IdP |
| POST | /auth/saml/callback | auth_saml.py:180 | N (SAML assertion) | ACS, JWT and refresh in redirect |
| GET/POST/PUT/DELETE | /scim/v2/Users[/{id}] | scim_router.py:120-201 | T (owner/admin) | SCIM user provisioning |
| GET | /scim/v2/Groups | scim_router.py:216 | T | org as a group |

### 5.2 Admin control plane
| Method | Path | File:line | Auth | Purpose |
|---|---|---|---|---|
| GET | /admin/users | admin_router.py:53 | A | paginated user list |
| POST | /admin/users/invite | admin_router.py:87 | A | create user with temp password (can grant owner) |
| POST | /admin/users/{id}/role | admin_router.py:107 | O | change role |
| POST | /admin/users/{id}/reset-password | admin_router.py:129 | A | temp password, force change |
| POST | /admin/users/{id}/deactivate | admin_router.py:147 | A | `is_active=False` |
| POST | /admin/users/{id}/reactivate | admin_router.py:163 | A | `is_active=True` |
| GET | /admin/audit/export.csv | admin_router.py:187 | A / S (cross-org) | streaming audit CSV |
| GET | /admin/error-registry | admin_router.py:298 | A | list error-registry entries |
| GET | /admin/error-registry/summary | admin_router.py:315 | A | per-category summary |
| POST | /admin/error-registry/{cat}/mark-fixed | admin_router.py:331 | S | record a fix |
| GET | /admin/platform-health | admin_platform_router.py:48 | A | Redis, active runs (platform-wide), disk |
| POST | /admin/kill-all | admin_platform_router.py:71 | O | cancel the org's running runs |
| POST | /admin/prune-artifacts | admin_platform_router.py:84 | A | **deletes `ARTIFACT_DIR` files for all tenants** |
| GET | /admin/audit-logs/export | admin_platform_router.py:121 | A | duplicate audit CSV |
| POST | /admin/system/deploy | admin_platform_router.py:197 | S | git stash and pull, pip install, `systemctl restart aetheros` |
| POST | /admin/platform/save-file | admin_platform_router.py:255 | S | overwrite a Guardian-monitored platform file |
| GET | /admin/platform/quality-metrics | admin_quality_router.py:42 | A | success rate, confidence |
| GET | /admin/platform/run-costs | admin_quality_router.py:144 | A | token costs from `llm_call_records` |
| GET | /admin/platform/phase-latency | admin_quality_router.py:232 | A | avg and p95 per phase |
| POST | /admin/runs/cleanup-council-review | run_spec_router.py:302 | A | **marks every org's** runs stuck >10 min in `council_review` as completed |
| GET | /system/feature-flags | system_info_router.py:200 | **N** | list flags |
| POST | /system/feature-flags/{flag} | system_info_router.py:207 | **N** | **sets `os.environ[FEATURE_*]`** |
| POST | /org/restore | account_settings_router.py:151 | O | unreachable: a deleted org gets 403 from `get_current_user` |
| DELETE | /org | account_settings_router.py:76 | O | soft-delete org, anonymise users |

### 5.3 Factory and runs (SDLC core)
| Method | Path | File:line | Auth | Purpose |
|---|---|---|---|---|
| POST | /factory/start | factory_start_router.py:131 | U (+RL) | trial and storage gates, rate limits, prompt guard, pre-insert Run, SQS or in-process background run |
| POST | /factory/estimate | factory_start_router.py:113 | U | static hosting-cost estimate |
| POST | /factory/upload-requirement | factory_intake_router.py:29 | U | parse txt, md, pdf, docx or image (LLM vision) |
| POST | /factory/fetch-github-repo | factory_intake_router.py:83 | U | pull key files through the GitHub API |
| POST | /factory/import-schema | factory_intake_router.py:123 | U | **connects to any postgres or mysql DSN** (SSRF) |
| POST | /factory/fetch-repo | factory_intake_router.py:150 | U | GitHub, GitLab (any base URL) or SSH `git clone` with a user key and `StrictHostKeyChecking=no` |
| GET | /factory/runs | factory_runs_router.py:93 | U | cursor-paginated run history |
| GET | /factory/runs/{id} | factory_runs_router.py:143 | U | detail, phases, disk outputs, security findings |
| GET | /factory/runs/{id}/test-report | factory_runs_router.py:78 | U | self-test report |
| GET | /factory/runs/{id}/quality | factory_runs_router.py:221 | U | quality score |
| POST | /factory/runs/{id}/priority | factory_runs_router.py:246 | U | `run_metadata.priority` |
| POST | /factory/runs/{id}/rerun | factory_runs_router.py:277 | U | new run from a phase (no rate limit or prompt guard) |
| POST | /factory/runs/{id}/branch | factory_runs_router.py:335 | U | fork a run (no trial or rate gate) |
| GET | /factory/runs/{id}/events | factory_runs_router.py:398 | U | `pipeline_events` |
| POST | /factory/runs/{id}/pause, /resume, /cancel | run_decisions_router.py:49,66,83 | U | Redis control flag |
| POST | /factory/runs/{id}/kill | run_decisions_router.py:100 | A, **I** (control flag set before the org check) | force cancel |
| POST | /factory/runs/{id}/restart | run_decisions_router.py:115 | U | resume from checkpoint |
| POST | /factory/runs/{id}/decisions/{did}/approve | run_spec_router.py:45 | U (engine checks org) | approve a gate, with Redis-history recovery |
| POST | /factory/runs/{id}/decisions/{did}/decide | run_spec_router.py:123 | U | approve or reject a gate |
| POST | /factory/runs/{id}/validate-spec | run_spec_router.py:149 | U | static spec lint |
| GET | /factory/runs/{id}/spec | run_spec_router.py:172 | U **I** | p01 requirements JSON |
| POST | /factory/runs/{id}/approve-spec | run_spec_router.py:194 | U **I** | release or cancel the spec_review gate |
| POST/GET | /factory/runs/{id}/council-review | run_spec_router.py:216,282 | U **I** | multi-LLM code review |
| GET | /factory/runs/{id}/decisions | factory_run_compliance_router.py:134 | U **I** | decision list |
| GET | /pipeline/status/{run_id} | factory_ops_router.py:43 | U | ledger detail (legacy) |
| POST | /pipeline/approve/{ticket_id} | factory_ops_router.py:57 | U | resolve a decision (legacy) |
| GET | /templates | factory_ops_router.py:93 | U | 12 static templates |
| POST | /factory/runs/{id}/sse-token | factory_run_streaming_router.py:31 | U | 30 s SSE token |
| GET | /factory/runs/{id}/stream | factory_run_streaming_router.py:45 | X | **SSE**: replay history (Last-Event-ID), then Redis pub/sub `pipeline:events:{id}`, with a fallback that polls the local buffer for up to 30 min |
| GET | /factory/runs/{id}/files | factory_run_files_router.py:79 | U | file tree |
| GET/PATCH | /factory/runs/{id}/file-content | factory_run_files_router.py:130,168 | U (viewers cannot write) | read or write project files (path-traversal guarded) |
| POST | /factory/runs/{id}/open-in-vscode | factory_run_files_router.py:195 | U | runs `code <dir>` on the server |
| GET/PATCH | /factory/runs/{id}/envvars | factory_run_files_router.py:211,246 | U | read or write the project `.env` |
| GET | /factory/runs/{id}/snapshots[/{sid}] | factory_run_files_router.py:277,308 | U | snapshot history |
| POST | /factory/runs/{id}/memory/changelog | factory_run_files_router.py:335 | U | changelog entry |
| POST | /factory/runs/{id}/feedback | learning_router.py:89 | U **I** | 1–5 star feedback |
| POST | /factory/runs/{id}/chat | run_preview_router.py:256 | U | project chat (`history` is built but never sent to the LLM) |
| GET/POST | /factory/runs/{id}/frontend-spec, /backend-spec | run_preview_router.py:184-233 | U | `run_specs` CRUD |
| GET | /factory/runs/{id}/traces[/{tid}] | run_preview_router.py:117,151 | U **I** | **full LLM prompts and responses from any tenant** |
| POST | /factory/runs/{id}/push-github | run_preview_router.py:39 | U | create a public repo, push up to 50 files |
| GET | /factory/analytics/quality-trend | factory_analytics_router.py:29 | U | per-run quality points |
| GET | /analytics/quality-trend | factory_analytics_router.py:186 | U | daily quality trend |
| GET | /factory/search | factory_analytics_router.py:109 | U | artifact semantic search |
| GET | /factory/deployments | factory_analytics_router.py:122 | U | runs plus `docker ps` |
| GET/POST/POST | /runs/{id}/questionnaires, /questionnaire/send, /questionnaire/fill | questionnaire_router.py:200,230,305 | U (ownership check passes when `run.org_id` is null) | guided-mode questionnaires |
| GET | /questionnaire/{token} | questionnaire_router.py:88 | Q | HTML or JSON form |
| POST | /questionnaire/{token}/submit | questionnaire_router.py:137 | Q | submit answers (resume is broken, §8.5) |
| GET | /questionnaire/{token}/status | questionnaire_router.py:175 | Q | completion status |

### 5.4 Deployment and preview
| Method | Path | File:line | Auth | Purpose |
|---|---|---|---|---|
| POST | /factory/runs/{id}/deploy | run_deploy_router.py:42 | U | p11 TaskAgent Docker deploy, or in-process preview |
| DELETE | /factory/runs/{id}/deploy | run_deploy_router.py:82 | U | `docker rm -f aetheros-app-{id8}` |
| GET | /factory/runs/{id}/artifacts | run_deploy_router.py:118 | U | artifact list |
| GET | /factory/runs/{id}/download | run_deploy_router.py:180 | U | ZIP download |
| POST | /factory/runs/{id}/run-app | run_app_router.py:88 | U (checked in the service; not verified here) | install, build and launch the generated app |
| DELETE | /factory/runs/{id}/run-app | run_app_router.py:98 | U **I** | kill another tenant's app |
| GET | /factory/runs/{id}/run-app/status | run_app_router.py:126 | U **I** | pid and port |
| GET | /factory/runs/{id}/preview-credentials | run_app_router.py:187 | U **I** | demo login credentials of the generated app |
| GET | /factory/runs/{id}/preview | run_app_router.py:245 | U | serve generated index.html (same origin) |
| ANY | /app-preview[/{path}] | app_preview_router.py:21 | **N** | proxy to the *most recently started* app, forwarding all headers; CSP `default-src *` |

### 5.5 Billing
| Method | Path | File:line | Auth | Purpose |
|---|---|---|---|---|
| GET | /billing/plans | billing_router.py:41 | N | static plans (INR) |
| POST | /billing/create-order | billing_router.py:81 | U | Razorpay order |
| POST | /billing/verify-payment | billing_router.py:108 | U | HMAC over order\|payment, then **sets plan from the request body** |
| GET | /billing/invoices | billing_router.py:143 | U | Stripe invoices |
| POST | /billing/cancel | billing_router.py:182 | U (any role) | cancel Stripe subscriptions, plan=free |
| POST | /billing/downgrade | billing_router.py:218 | U (any role) | **sets plan to anything in {free, trial, starter, pro, enterprise}** |
| POST | /billing/webhook | billing_router.py:236 | W (Razorpay) | upgrade on payment.captured |
| POST | /billing/stripe/checkout | billing_stripe_router.py:59 | U | Checkout Session (caller-supplied success URL) |
| POST | /billing/stripe/webhook | billing_stripe_router.py:109 | W (Stripe) | upgrade on checkout completed, free on subscription deleted |
| GET | /billing/stripe/portal | billing_stripe_router.py:163 | U | Customer Portal |
| GET | /pricing | system_info_router.py:157 | N | static HTML (₹2,00,000 Pro, which contradicts /billing/plans) |

### 5.6 Compliance and audit
| Method | Path | File:line | Auth | Purpose |
|---|---|---|---|---|
| GET | /audit/logs | compliance_router.py:54 | A | paginated ledger |
| GET | /audit/logs/export | compliance_router.py:65 | A | JSON or CSV, up to 10k rows, ≤365 days |
| DELETE | /audit/logs/purge | compliance_router.py:102 | A | delete rows older than N days (≥30); breaks the prev_hash chain |
| GET | /compliance/artifacts/{run_id} | compliance_router.py:123 | U **I** | compliance JSON and PDF ZIP; scans any run's main.py |
| GET | /compliance/org-report | compliance_router.py:173 | U | runs, decisions, EU AI Act risk level, region |
| GET | /factory/runs/{id}/compliance | factory_run_compliance_router.py:31 | U **I** | read, or create and write, the run's compliance scan |
| GET | /factory/runs/{id}/portal | factory_run_compliance_router.py:148 | U | portal deliverables |
| GET | /account/data-export | account_router.py:85 | U | GDPR export (user, runs, 500 audit rows) |
| DELETE | /account | account_router.py:126 | U | GDPR erasure (anonymise and deactivate) |
| GET | /legal/tos, /legal/privacy, /legal/dpa | legal_router.py:13,49,90 | N (IP RL) | legal texts |

### 5.7 Guardian, SRE and observability
| Method | Path | File:line | Auth | Purpose |
|---|---|---|---|---|
| GET | /health | health_router.py:30 | N | liveness |
| GET | /health/zero-trust | health_router.py:42 | N | probe of the HMAC ticket system |
| GET | /health/observability | system_info_router.py:27 | N | LangSmith status |
| GET | /health/sla | system_info_router.py:34 | U | 30-day completion rate, p50 and p95 |
| GET | /system/metrics | system_router.py:39 | **N** | CPU, memory, disk, DB, Redis, platform active runs |
| GET | /system/status | system_router.py:83 | N | static ok |
| GET | /system/health | system_router.py:87 | U | LLM providers, DB, Redis, docker, workloop |
| GET | /system/workloop | system_router.py:240 | U | workloop monitor detail |
| GET | /system/costs | system_info_router.py:97 | U | token budget, cache stats |
| GET | /metrics | metrics_router.py:27 | K | Prometheus |
| GET | /_metrics_internal | api.py:150 | **N** | Prometheus (Instrumentator expose) |
| GET | /guardian/status | guardian_router.py:43 | N / U | threat level. **Bug:** it calls `get_current_user(credentials)` with the wrong argument order, so every caller gets the public stub |
| GET | /guardian/stats | guardian_router.py:113 | U | prevention counters |
| GET | /guardian/events | guardian_router.py:136 | A | event log |
| POST | /guardian/scan | guardian_router.py:182 | U (any role) | runs a **platform-wide** threat scan |
| POST | /guardian/events/{id}/resolve | guardian_snapshots_router.py:40 | A | resolve an event |
| GET/POST | /guardian/snapshots | guardian_snapshots_router.py:76,94 | S | list or take DB snapshot |
| POST | /guardian/restore/{sid} | guardian_snapshots_router.py:113 | S | restore the platform DB |
| POST | /guardian/update-baseline | guardian_snapshots_router.py:137 | S | file-integrity baseline |
| GET | /admin/platform-health | (§5.2) | A | |

### 5.8 Org, account and settings
| Method | Path | File:line | Auth | Purpose |
|---|---|---|---|---|
| GET | /account/usage, /account/storage, /account/projects, /account/projects/search | account_router.py:41,56,67,76 | U | usage and project listing |
| GET/PUT | /account/preferences | account_router.py:158,188 | U | `users.user_preferences` |
| POST/GET | /account/settings | account_settings_router.py:32,56 | U (**no role check** on POST) | decision_mode, autonomous_mode, org_name, data_region |
| GET | /orgs/me/usage | account_settings_router.py:122 | U | billing-panel usage |
| POST | /account/import-codebase | account_codebase_router.py:134 | U | GitHub tree into CodebaseProfile |
| GET | /account/codebase-profiles | account_codebase_router.py:249 | U | list profiles |
| GET | /settings/active-provider, /settings/models | settings_router.py:58,71 | U | LLM provider and model list |
| POST | /settings/models/test | settings_router.py:98 | U | stub, always `{success:true}` |
| GET/POST | /settings/api-keys | settings_router.py:109,136 | U / A | org BYO LLM keys (Fernet-encrypted) |
| GET/POST | /settings/langsmith | settings_router.py:168,187 | U / A | LangSmith opt-in |
| POST | /settings/test-provider | settings_router.py:218 | U | live provider test; **falls back to the platform env key** |
| GET/PUT | /settings/llm-config | settings_advanced_router.py:57,92 | U / A | `llm_config` |
| GET/PUT | /settings/council-config | settings_advanced_router.py:124,138 | U / A | council enable and strict mode |
| POST | /settings/phases/{name}/config | settings_advanced_router.py:163 | U (**no role check**) | enable or disable phases per org |
| GET | /settings/phases/config | settings_advanced_router.py:181 | U | list phase configs |
| GET/PUT | /settings/preferences | settings_advanced_router.py:194,203 | U | memory_service preferences (a second store, separate from /account/preferences) |
| GET/PUT/DELETE | /settings/sso | settings_advanced_router.py:216,238,253 | U (**no role check on PUT or DELETE**) | per-org SAML IdP config |
| GET | /settings/scim | settings_advanced_router.py:266 | U | whether a token is configured, base URL |
| POST | /settings/scim/rotate | settings_advanced_router.py:280 | O | new SCIM token |
| CRUD | /workspaces[/{id}] | workspaces_router.py:38-130 | U | workspaces |
| GET/POST | /notifications, /notifications/read-all, /notifications/{id}/read | notifications_router.py:21,51,67 | U | in-app notifications |

### 5.9 API management: webhooks, keys, MCP, plugins, marketplace
| Method | Path | File:line | Auth | Purpose |
|---|---|---|---|---|
| GET/POST | /webhooks | webhooks_router.py:25,43 | U | outbound webhooks (SSRF check on create, IP literals only) |
| PUT | /webhooks/{id} | webhooks_router.py:100 | U | **changes the URL with no SSRF check** |
| DELETE | /webhooks/{id} | webhooks_router.py:87 | U | delete |
| POST | /webhooks/{id}/test | webhooks_router.py:119 | U | server-side POST to the stored URL (SSRF) |
| GET | /mcp/list_runs | mcp_router.py:41 | J | runs from legacy `~/.aether_os/aether_os.db` (SQLite) |
| GET | /mcp/get_run_status/{id} | mcp_router.py:59 | J **I** | phase status |
| GET | /mcp/get_artifact/{id}?file_path= | mcp_router.py:77 | J **I** | read any project's file |
| POST | /mcp/start_pipeline | mcp_router.py:98 | J | starts a factory run with **no trial, rate or prompt-guard checks** |
| GET | /mcp/get_architecture/{id} | mcp_router.py:118 | J **I** | architecture doc |
| GET | /v2/plugins/catalog[/{id}] | plugins_router.py:45,58 | U | plugin catalog |
| GET | /v2/plugins/installed | plugins_router.py:73 | U | installed plugins |
| POST | /v2/plugins/install | plugins_router.py:96 | U | install a plugin (plan-gated in the registry) |
| DELETE/PUT/POST | /v2/plugins/installed/{id}, /config, /test | plugins_router.py:122,135,149 | U (any role) | uninstall, set credentials, test |
| POST | /v2/plugins/connectors/invoke | plugins_router.py:175 | U | run a connector action |
| POST/GET | /v2/plugins/skills/generate, /v2/plugins/skills | plugins_connectors_router.py:88,119 | U | skill code generation |
| POST/GET | /v2/plugins/connectors/salesforce/* (4 routes) | plugins_connectors_router.py:132-180 | U | **calls any `instance_url`**; access token sent in the query string on GET |
| POST | /v2/plugins/connectors/ldap/validate, /users, /authenticate | plugins_connectors_router.py:198,215,239 | U | **binds to any LDAP server** |
| GET | /marketplace/installed | marketplace_router.py:26 | U | org installs |
| GET | /marketplace/profiles[/{id}] | marketplace_router.py:62,89 | **N** | published profiles |
| POST | /marketplace/publish | marketplace_router.py:104 | U (any role) | publish (`is_published=True` immediately, no review) |
| POST | /marketplace/install/{id} | marketplace_router.py:127 | U | increments usage and starts a run via pipeline_service |
| PUT/DELETE | /marketplace/profiles/{id} | marketplace_router.py:170,187 | U / A | edit or delete own profile |
| GET | /agents | agents_router.py:22 | U | registered agents |
| POST | /agents/{name}/run | agents_router.py:40 | U | runs an agent with a **caller-chosen `project_path`** (arbitrary server path) |

### 5.10 Intelligence, learning and memory
| Method | Path | File:line | Auth | Purpose |
|---|---|---|---|---|
| GET | /intelligence/global-insights | intelligence_router.py:38 | U | org patterns plus a **cross-org** domain histogram |
| GET/POST/PUT/DELETE | /intelligence/global-patterns[/{id}] | intelligence_router.py:91-163 | U / A | GlobalPattern CRUD |
| GET | /intelligence/quality-benchmark | intelligence_router.py:180 | U | domain scores |
| POST | /intelligence/arch-governor/review, /truth-engine/validate, /conflict-resolver/detect, /conflict-resolver/resolve, /tradeoff-engine/analyze, /improvement-loop/cycle, /maintenance-engine/scan | intelligence_router.py:208-283 | U (`run_id` variants **I**) | T9 engines (LLM spend) |
| GET | /intelligence/maintenance-engine/health/{run_id} | intelligence_router.py:298 | U **I** | project health |
| GET | /learning/context, /learning/clarifications | learning_router.py:33,46 | U | personalisation |
| POST | /learning/clarifications/{id}/answer | learning_router.py:63 | U | answer a clarification |
| GET | /learning/stats, /learning/golden-builds | learning_router.py:112,119 | U | **global** (not org-scoped) |
| POST | /memory/search | memory_router.py:22 | U | similar-run search (org-scoped) |
| GET | /memory/graph | memory_router.py:57 | U | **global** memory store (input text from other orgs) |

### 5.11 Client portal, CI/CD and static
| Method | Path | File:line | Auth | Purpose |
|---|---|---|---|---|
| GET | /portal/{id}/status | client_portal/routes.py:128 | **N** | requirements text, phases, compliance score |
| GET | /portal/{id}/phase/{phase_name} | client_portal/routes.py:218 | **N** | phase files (≤5 KB each); `phase_name` is not sanitised |
| POST | /portal/{id}/approve | client_portal/routes.py:236 | P | **no-op stub**: logs and returns a message |
| POST | /portal/{id}/feedback | client_portal/routes.py:256 | P | append to `feedback.jsonl` |
| GET | /portal/{id}/download | client_portal/routes.py:353 | **N** (the run UUID acts as the secret) | full project ZIP |
| GET | /portal/{id}/provenance | client_portal/routes.py:432 | **N** | provenance Markdown (ledger lookup with `org_id=None`) |
| POST | /ci/webhook | phases/p08_cicd/webhook.py:96 | **N** (no HMAC) | queues a self-healing repair job; caller-supplied `repo_root` builds a call graph from any server path |
| GET | /ci/jobs/{job_id} | phases/p08_cicd/webhook.py:143 | N | repair job status |
| GET | / | health_router.py:81 | N | landing page or redirect to `/dashboard/` |
| GET | /favicon.ico, /favicon.svg | health_router.py:90 | N | favicon |
| GET | /dashboard[/{path}] | spa_router.py:35 | N | SPA with nonce injection |
| GET | /docs, /redoc, /openapi.json | FastAPI | N (not in production) | API docs |

---

## 6. Data model

### 6.1 Tables (ORM is the source of truth: `core/models.py`, `core/guardian/models.py`)
| Table | Key columns | Relationships and notes |
|---|---|---|
| organisations | id (VARCHAR 50, `org_` prefix after 2559620361b4), name, slug UQ, plan, trial_runs_used/limit, storage_used_mb, autonomous_mode, decision_mode*, data_region, scim_token (legacy plaintext), scim_token_hash, stripe_customer_id, is_deleted, deleted_at, updated_at | 1:N users, api_keys, runs. *`decision_mode` is added by migration d26b82 but is **not mapped in `core/models.py`** (verified by grep), so `POST /account/settings {decision_mode}` breaks the `update()` call |
| users | id, org_id FK, email **UQ global**, password_hash, role, is_active, user_preferences (JSON text), consent_at, deleted_at, mfa_secret (EncryptedText), mfa_enabled, email_verified, must_change_password, updated_at | global email uniqueness drives the OAuth, SAML and SCIM lookups |
| api_keys | id, org_id FK, key_hash (sha256), name, last_used_at, is_active, created_at | no scopes or expiry |
| runs | id, org_id FK, user_id (36; written with **email** from `sub` at `factory_start_router.py:287`), command, raw_input, requirement, project_name, domain, client_id, status, current_phase, message, phases JSON, started_at/finished_at (epoch float), live_url, cost, run_version, parallel_run_group_id, self_test_report, council_preflight/delivery, parent_run_id, branch_phase, quality_score, checkpoint_data JSON(B) | 1:N events, snapshots, phase_completions (cascade). **No `accumulated_context` column**, which the questionnaire code expects |
| events | id, run_id FK, agent, action, detail, timestamp | legacy event log |
| pipeline_events | id, run_id FK cascade, event_type, payload JSON, created_at | persisted SSE events |
| phase_completions | (run_id FK, phase_name) PK, status, duration_s, updated_at | |
| snapshots | id, run_id FK, file_path, content, created_at | code version history |
| run_metadata | run_id PK, priority, updated_at | no FK |
| run_specs | (run_id FK, spec_type) PK, spec JSON | **no migration creates it** |
| decisions | id, run_id, org_id, decision_type, title, what, why, alternatives, impact, phase, status, human_choice, timeout_seconds, created_at, decided_at | no FK; created twice in migrations, as Float and as DateTime |
| phase_configs | (org_id, phase_name) PK, enabled int, priority | |
| audit_log | id, org_id, user_id, action, resource_type, resource_id, log_metadata, ip_address, created_at float, prev_hash | hash chain; **no migration creates the table**; purgeable through the API |
| saml_configs | id, org_id UQ, idp_entity_id, idp_sso_url, idp_cert | |
| webhooks | id, org_id, url, events JSON, secret (nullable, deprecated), secret_hash, is_active, last_triggered_at | |
| workspaces | id, org_id, name, description, preferences, created_by, is_shared | |
| org_api_keys | id, org_id, provider, api_key (EncryptedText), updated_by; UQ (org_id, provider) | BYO LLM keys |
| llm_config | id, org_id, provider, heavy/light_model, prefer_paid, council_enabled/strict, langsmith_*, bedrock_* | migration comment says "intentionally unused at runtime", but settings routes use it |
| llm_call_records | id, org_id, project_id, phase, model, input/output_tokens, cost_usd | **no migration creates it** (2b2463983a2a only alters it) |
| token_budget_records | id, org_id, month, tokens, runs, cache hits/misses, estimated_cost_usd | |
| llm_cache_entries | cache_key PK, task_type, response, prompt_tokens, hit_count | |
| llm_traces | id, run_id FK cascade, phase, task_type, model, prompt, raw_response, parsed_ok, tokens | full LLM I/O; no org_id column (hence the IDOR in §5.3) |
| artifact_embeddings | id, run_id, org_id FK cascade, file_path, content_hash, embedding JSON, embedding_vector (pgvector 1536, optional) | |
| marketplace_profiles | id, org_id, name, base_domain, price_usd, profile_yaml, is_published, usage_count | |
| installed_plugins | id, org_id, plugin_id, config_json, test_status | |
| global_patterns | id, org_id FK, domain, pattern_name/type, success_rate, usage_count, avg_quality_score | the migration has no org_id |
| user_learning_patterns | id, org_id FK, user_id FK, pattern_type/key/value, confidence | **no migration creates it** |
| learning_clarifications_pending | id, org_id, user_id, run_id FK set null, question, answer JSON, expires_at | |
| build_feedback | id, run_id FK cascade, org_id, user_id, rating, tags, comment | |
| golden_builds | id, run_id, org_id ("system" for seed rows), domain, quality_score, samples, domain_ir_summary, is_active | |
| codebase_profiles | id, org_id FK, repo_url, repo_name, detected_stack, file_tree, summary | |
| notifications | id, org_id, user_id (null means org-wide), type, title, message, link, is_read | |
| questionnaire_sessions | id, run_id FK cascade, stage_id, status, access_token UQ, token_expires_at, respondent_*, agency_*, questions, answers, submitted_at | |
| guardian_events | id, event_type, severity, source_ip, endpoint, detail JSON, **org_id** (ORM only, no migration), resolved, created_at TZ | |
| guardian_snapshots | id, snapshot_path, size_bytes, integrity_hash, trigger, status, db_backend | |
| org_code_profiles | (migration 4d5c94 only) | **orphan**: in migrations, not in the ORM |

### 6.2 Relationships
- Organisation → Users, APIKeys, Runs; Run → Events, Snapshots, PhaseCompletions (ORM cascade).
- FK only, no ORM relationship: codebase_profiles, global_patterns, user_learning_patterns, artifact_embeddings → organisations; pipeline_events, llm_traces, build_feedback, questionnaire_sessions, run_specs, learning_clarifications → runs.
- Logical only (plain `org_id` string, no FK): decisions, webhooks, workspaces, org_api_keys, audit_log, saml_configs, marketplace_profiles, installed_plugins, token_budget_records, llm_call_records, notifications, golden_builds, guardian_events.

### 6.3 Migration chain
- Root: `f9f084df3f49` (baseline: phase_configs, run_metadata, runs, events, phase_completions, snapshots). Single **head**: `revision_pgvector_artifact_embedding`. No missing parents.
- **Linearised trunk** (merges shown in brackets):
  - `f9f084df3f49` → {`4688c33ff6e8` multi-tenancy (organisations, users, api_keys, runs.org_id) ‖ `revision_09ddf4a23dc0` saml_configs → `revision_1ef04e14f9d0` webhooks, run_version, storage_used_mb}
  - → [`f3248d2ed62b`, `ea230bec6fc8`] → {`revision_85f8b596aaf5` autonomous_mode, self_test_report ‖ `revision_d26b82ffa45c` decisions and decision_mode → `revision_a6ed6297ffcf` parallel_run_group_id}
  - → [`ffd126a9bb7f`] → `revision_4d5c94389944` marketplace_profiles and org_code_profiles → `revision_474970353032` data_region → `revision_d6973beef17f` workspaces and user_preferences → `23e65878ea04` "final_sync" (**re-adds** runs.org_id, parallel_run_group_id, self_test_report)
  - → {`3815540c9443` (**re-creates** decisions, marketplace_profiles, saml_configs, webhooks, workspaces; adds artifact_embeddings and global_patterns) → `revision_e1f2a3b4c5d6` council columns and llm_config ‖ `revision_b1c2d3e4f5a6` phase_configs org PK and FK indexes}
  - → [`cda442e061e6`] → `revision_f7a8b9c0d1e2` parent_run_id, branch_phase → `revision_add_user_id_runs` → `revision_add_quality_score_runs` → `revision_add_artifact_embedding_org_id` (index) → `revision_add_org_api_keys` → [`merge_heads_final`, a redundant merge because one parent is the other's ancestor]
  - → `revision_guardian_module` guardian_events and guardian_snapshots → {`add_artifact_embedding_org_fk` ‖ `revision_guardian_timestamptz` ‖ `encrypt_sensitive_columns` (Fernet re-encrypts org_api_keys.api_key and users.mfa_secret; **requires AETHER_FIELD_KEY**)}
  - → [`revision_merge_guardian_heads`] → three branches:
    - `a1b2c3d4e5f6` llm_traces
    - `add_org_scim_token` → `add_codebase_profiles` → `add_audit_log_prev_hash` → `add_stripe_customer_id` → `add_pipeline_run_checkpoint` → `add_golden_builds_feedback` → `add_learning_clarifications`
    - `revision_events_timestamp_idx`
  - → [`7396e586c3d4` merges a1b2, learning_clarifications and encrypt; `08426bb9c4b3` merges that with events_timestamp_idx]
  - → `f6cf580e353c` (autogenerated: **re-creates** golden_builds, org_api_keys, codebase_profiles, build_feedback and llm_traces; re-adds prev_hash, scim_token, stripe_customer_id, quality_score and checkpoint_data; adds users.email_verified) → `3a646dd3b217` org soft delete → `2559620361b4` org id VARCHAR(50) plus `org_` prefix rewrite across 24 tables (Postgres-only raw SQL) → `44e860b77fc6` llm_config langsmith and bedrock → `2b2463983a2a` llm_call_records.org_id (guarded) → `add_questionnaire_sessions`
  - Side branch from `revision_merge_guardian_heads`: `add_must_change_password` → `add_scim_token_hash`. Side branch from `revision_events_timestamp_idx`: `revision_add_missing_tables` (llm_cache_entries, token_budget_records, installed_plugins, pipeline_events, notifications).
  - → [`merge_heads_m3_m4_m5_m7`: questionnaire, scim_token_hash, missing_tables, org_api_keys (again redundant)] → `add_webhook_secret_hash` → `add_audit_log_org_id_index` → `add_saml_config_unique_org_id` → `add_updated_at_org_user` → **`revision_pgvector_artifact_embedding`** (Vector(1536), only when pgvector is importable).
- **Merge nodes (8):** f3248d2ed62b, ea230bec6fc8, ffd126a9bb7f, cda442e061e6, merge_heads_final, revision_merge_guardian_heads, 7396e586c3d4, 08426bb9c4b3, and merge_heads_m3_m4_m5_m7. That makes 9 if `08426` is counted separately; it is the second merge in the same step.
- Docstring vs code mismatches in `Revises:`: `add_pipeline_run_checkpoint` (docstring says encrypt and scim, code says `add_stripe_customer_id`), `revision_add_org_api_keys`, and `revision_f7a8b9c0d1e2`.
- Dialect issues: `2559620361b4`, `revision_guardian_timestamptz` and `add_artifact_embedding_org_fk` use Postgres-only SQL, while `env.py` sets `render_as_batch` for SQLite.

---

## 7. Plane mapping

| Plane | Gateway components |
|---|---|
| **API management** | `api.py` router table and required/optional flags; CORS, GZip and security-header middleware; `/api` prefix strip; `/v2` prefix for plugins only; rate limiting (login, register, password reset and MFA by IP; factory start per org per minute, per hour and concurrent in Redis, plus a DB cap of 3 per org and 10 platform-wide, `factory_start_router.py:87-108`; public legal endpoints by IP); org API keys (`auth_keys_router`); outbound webhooks (`webhooks_router`, lifespan cleanup); MCP REST facade (`mcp_router`); SSE streaming with single-use tokens; plugins and connectors; marketplace; OpenAPI disabled in production. No API versioning beyond `/v2/plugins`, no per-key quotas, no idempotency keys. |
| **Admin control** | `admin_router`, `admin_platform_router` (git deploy, platform file write, prune, kill-all), `admin_quality_router`, `run_spec_router` cleanup, `system_info_router` feature flags (unauthenticated), `settings*` (org config), `account_settings_router` (org delete and restore), Guardian snapshot restore, `admin_service`. |
| **Security** | `auth.py` and `dependencies.py` (JWT, API keys, blacklist), MFA, OAuth, SAML, SCIM, `SecurityHeadersMiddleware` (CSP nonce, HSTS), `HttpsRedirect`, password shield (HIBP), prompt guard on `/factory/start`, SSRF guards (webhooks create, fetch-repo GitLab), path-traversal guard (`_safe_file_path`), field encryption key check, Guardian routes (threat events, scan, baseline). |
| **Compliance** | `compliance_router` (audit ledger, export, purge, compliance ZIP, org report including EU AI Act risk), `factory_run_compliance_router`, embargo and jurisdiction pre-check (`factory_run_background.py:139-275`), GDPR export and erasure (`account_router`), ToS and DPA consent capture at registration, legal texts, audit middleware, `audit_log.prev_hash` chain. |
| **SRE** | `lifespan` (fail-fast dependency checks, crash recovery, app auto-restore, watchdog, workloop monitor, SQS consumer), health, zero-trust and observability endpoints, `/system/*`, `/metrics` and `/_metrics_internal`, Sentry, structlog org binding, SLA endpoint, Guardian snapshot and restore. |
| **Deployment** | `run_deploy_router` (Docker through the p11 TaskAgent, or in-process fallback), `run_app_router` and `app_preview_router` (generated-app hosting), `/factory/deployments`, push-github, `/admin/system/deploy` (self-update of the platform), CI webhook. |
| **SDLC** | `factory_start`, intake, runs, decisions, spec, files, streaming, analytics; questionnaire (guided mode); background runner and post-build hooks. |
| **STLC** | `/factory/runs/{id}/test-report`, quality score endpoints, council review, admin quality metrics, the p08 CI repair webhook. |
| **Billing and monetisation** | Razorpay (India) and Stripe routers, trial counter, storage limits, plan-gated models and plugins. |
| **Data and learning** | intelligence, learning, memory, golden builds, GlobalPattern. |

---

## 8. Reality check

### 8.1 Critical (exploitable as the code stands)
1. **Unauthenticated control-plane writes.** `POST /system/feature-flags/{flag}` changes `os.environ` (`system_info_router.py:207`). `POST /ci/webhook` queues LLM repair jobs and builds a call graph from any `repo_root` path (`p08_cicd/webhook.py:96`); `gateway/security.py` contains HMAC verifiers that are never used.
2. **`/_metrics_internal` is unauthenticated** (`api.py:150`), which defeats the key protection on `/metrics`.
3. **Refresh token accepted as an access token.** `dependencies.py` never checks `token_type`. Refresh tokens are not rotated or revoked (`auth_refresh_router.py`) and logout leaves them valid.
4. **SAML cross-tenant account takeover.** `PUT /settings/sso` has no role check (`settings_advanced_router.py:238`), and any registered user owns their own org anyway. An attacker who registers a malicious IdP can assert `email=victim@...` and set the RelayState `org` to their own slug. The callback then looks the user up by **global** email and issues the victim's JWT (`auth_saml.py:249`). OAuth upserts by email too, but those providers verify emails.
5. **Billing bypass.** `POST /billing/downgrade` accepts `pro` and `enterprise` (`billing_router.py:217`). `verify-payment` takes `plan` from the request, so paying for Pro can unlock Enterprise (`:114`). No role check on cancel or downgrade.
6. **Same-origin untrusted code.** `/app-preview/*` is unauthenticated, serves the last-started tenant's generated app on the platform origin with `default-src * 'unsafe-inline' 'unsafe-eval'`, and is exempted from the security headers (`app_preview_router.py:129`, `api_helpers.py:150`). The dashboard stores `aether_token` and `aether_refresh_token` in `localStorage` (`dashboard/src/api.js:21,40`), so generated JS can read them. The proxy also forwards the caller's `Authorization` header to the generated app (`:119-123`), and a ConnectError triggers `start_run_app` as a synthetic admin.
7. **IDOR (no org check)**, all reachable by any authenticated user:
   - `/factory/runs/{id}/traces[/{tid}]` (full prompts)
   - `/factory/runs/{id}/compliance` (reads and writes another tenant's directory)
   - `/factory/runs/{id}/decisions`
   - `/factory/runs/{id}/spec`, `/approve-spec`, and GET/POST `/council-review`
   - `/factory/runs/{id}/run-app` DELETE and `/status`
   - `/factory/runs/{id}/preview-credentials`
   - `/factory/runs/{id}/feedback`
   - `/compliance/artifacts/{id}`
   - `/intelligence/*` routes that take a `run_id`
   - `/mcp/get_run_status`, `/get_artifact`, `/get_architecture`
   - `/factory/runs/{id}/kill` (control flag set before the org-scoped update)
8. **Unauthenticated tenant data.** `/portal/{id}/status`, `/phase/*`, `/download` (whole project ZIP) and `/provenance` rely only on the run UUID being secret. `/system/metrics` exposes platform load.
9. **SSRF and server-side reach.**
   - `/factory/import-schema` connects to any Postgres or MySQL DSN, including the platform's own database host.
   - `/factory/fetch-repo` runs SSH `git clone <user url>` with no `--` separator (argument injection) and `StrictHostKeyChecking=no`.
   - Salesforce and LDAP connectors call caller-supplied hosts.
   - `PUT /webhooks/{id}` skips the SSRF check; the create-time check only validates IP literals and is defeated by DNS.
   - `/agents/{name}/run` accepts an arbitrary `project_path`.
   - `/factory/runs/{id}/open-in-vscode` executes `code` on the server.
10. **Privilege paths.** Admins can invite owners and reset an owner's password. Members can change org settings (`POST /account/settings`), phase config, and SSO. `/admin/prune-artifacts` (admin of any org) deletes artifacts for **all** tenants. `/admin/runs/cleanup-council-review` updates every org's runs.

### 8.2 Functional bugs found while reading
- `guardian_router.py:53` calls `get_current_user(credentials)` while the signature is `(request, credentials)`, so authenticated users always receive the stub.
- `questionnaire_helpers.py:37-44` reads and writes `Run.accumulated_context`, which does not exist in `core/models.py`. The exception is swallowed, so **guided-mode answers never reach the pipeline**.
- `factory_start_router.py:287` stores `user_id = sub` (an email) in `runs.user_id VARCHAR(36)`. Long emails make the pre-insert fail; the failure is swallowed.
- `run_preview_router.py:296-308`: chat builds `conversation` and then ignores it.
- `scim_router.py:197`: `displayName` overwrites `user_preferences`.
- `/org/restore` is unreachable because a deleted org's users get 403 from `get_current_user`, and the users have already been anonymised.
- `/portal/{id}/approve` is a stub (`client_portal/routes.py:243-251`).
- OAuth CSRF state is per process, so multi-worker deployments fail.
- `/api/health` (`health_router.py:31`) and `api_router` (`api.py:220`) are unreachable because of `strip_api_prefix`.
- `pyotp` (`auth_mfa.py:29`) and `razorpay` and `stripe` (`billing_router.py:24-25`) are imported at module top level. `billing` is a **required** router, so a missing payment SDK aborts startup.
- MCP reads the legacy SQLite `~/.aether_os/aether_os.db`, not Postgres, so on a Postgres deployment it returns empty or stale data.

### 8.3 Size rules
- Routers over 400 lines: `factory_runs_router.py` (439, pre-approved) and `client_portal/routes.py` (452, not approved).
- Close to the limit: `factory_run_background.py` (393), `factory_start_router.py` (391).
- No gateway file is over 600 lines; the largest is 452.
- Several modules import the same names repeatedly with aliases (`compliance_router.py:19-35`, `billing_router.py:17-26`, `admin_platform_router.py:28-43`, `system_router.py:15-34`). This cosmetic debt comes from mechanical file splits.

### 8.4 Unmounted or dead code
- Every router file in `gateway/routers/` is mounted.
- DEAD: `gateway/security.py`; `auth.verify_token_dependency`; the 14 Pydantic models re-exported from `api_helpers.py` (routers define their own copies); `_APP_PROCS` and `_APP_PORTS` in `api.py:88`; the `/dashboard` StaticFiles mount (shadowed by the SPA router); the SPA "missing" branch, which only exists when the dist folder is absent.
- Optional routers fail silently: an import error in `scim`, `mfa`, `oauth`, `saml`, `compliance`, `guardian` and others only logs a warning (`api.py:301`), so security features can vanish with no visible signal.

### 8.5 Alembic reality
- **The chain is not replayable from scratch.** Examples of duplicate DDL: `decisions`, `webhooks`, `workspaces`, `saml_configs` and `marketplace_profiles` are created twice (by d26b82, 1ef04e, d6973b, 09ddf4 and 4d5c94, then again by 3815540c9443). `23e65878ea04` re-adds 3 `runs` columns. `f6cf580e353c` re-creates 5 tables and re-adds 6 columns.
- `audit_log`, `llm_call_records`, `user_learning_patterns` and `run_specs` are altered by migrations but never created by any of them. `guardian_events.org_id` and most `users` columns (is_active, consent_at, deleted_at, mfa_secret, mfa_enabled) have no migration either.
- Production must be relying on `init_db()` create_all plus `alembic stamp`. That puts `DATA_MODEL.md`'s statement that "All tables are managed via Alembic migrations" in doubt.
- `encrypt_sensitive_columns` raises when `AETHER_FIELD_KEY` is missing.

### 8.6 Drift between docs and code
**`API_REFERENCE.md`:**
- Documents about 75 of about 282 endpoints. It is missing admin platform, billing, compliance, Guardian, SCIM, SAML, OAuth, MFA, MCP, marketplace, intelligence, questionnaire, portal, webhooks and most settings routes.
- The entire `/v2/auth/*` and `/v2/factory/*` sections, including `/v2/factory/projects/{id}/change-request` (lines 618-856), **do not exist**. Only `/v2/plugins/*` is real.
- Login: the docs show a `totp_code` field (line 57). The code uses a separate `mfa_token` and `/auth/mfa/confirm` step.
- Register: the docs show `full_name`, status 201, and a nested `user` object. The code takes `name`, requires `terms_accepted` and `dpa_accepted`, returns 200, and returns a flat `LoginResponse`.
- Logout: the docs say "revokes refresh token". The code only blacklists the access-token jti.
- SSE: the docs say `?token=`. The code uses `?sse_token=` (line 216).
- `/health`: the docs say `version` is "2.0.0". The code returns "1.0.0".
- The `/system/metrics` response shape differs from the docs.
- Login rate limit: the docs say "5 attempts/minute". The real value lives in `core.rate_limiter`, and the code message says 15 minutes.
- `/system/metrics` is described as nginx-restricted; nothing in the code restricts it.

**`DATA_MODEL.md`:**
- Lists 25 tables; the ORM has 35. Missing: org_api_keys, artifact_embeddings, pipeline_events, llm_traces, questionnaire_sessions, codebase_profiles, build_feedback, golden_builds, learning_clarifications_pending, guardian_events, guardian_snapshots, and others.
- Ids are documented as VARCHAR(36) UUIDs; org ids are actually VARCHAR(50) with an `org_` prefix.
- Columns missing from the doc: users.email_verified, must_change_password, updated_at; organisations.scim_token_hash, is_deleted, deleted_at, updated_at, decision_mode; webhooks.secret_hash (and `secret` is now nullable); audit_log.prev_hash.
- `mfa_secret` is documented as VARCHAR(64); it is EncryptedText.
- "audit_log append-only, never deleted" is contradicted by `DELETE /audit/logs/purge`.
- "No cross-org queries" is contradicted by `/intelligence/global-insights`, `/memory/graph`, `/learning/stats`, `/learning/golden-builds`, `/admin/prune-artifacts` and `/admin/runs/cleanup-council-review`.
- Legal privacy text (`legal_router.py:81`) says `PUT /api/account/settings`; the real method is POST.

---

## 9. Open questions
1. How is `role="superadmin"` granted? Neither `core/models.py` nor `core/seed.py` mentions it, so it is presumably set by hand in the DB. Is the demo user (`demo@aetheros.ai`) a superadmin in production?
2. Does `core.services.run_app_service._launch_generated_app` enforce run ownership? `start_run_app` delegates without checking. Lifespan and app-preview call it with `org_id=None` as an admin.
3. Is the production schema created by `init_db()` and then `alembic stamp head`? Without that, §8.5 means `alembic upgrade head` fails on a fresh database.
4. Does nginx strip or overwrite `X-Forwarded-For` and `X-Real-IP`? Every IP rate limit and audit IP depends on it. Does nginx block `/_metrics_internal`, `/system/*`, `/ci/*` and `/app-preview`?
5. How are outbound webhooks signed when only `secret_hash` (bcrypt) is stored (`webhooks_router.py:71-79`)? The delivery code is outside this scope.
6. `organisations.decision_mode` exists in migration d26b82 and is allow-listed in `/account/settings`, but `core/models.py` does not map it, so `update(Organisation).values(decision_mode=...)` should raise. Is the column read anywhere through raw SQL?
7. Is the `AETHER_SECRET_KEY` HS256 "migration window" (`auth.py:216-233`) meant to be permanent? It weakens RS256 to the strength of a shared secret.
8. `admin_router` export allows `superadmin` to read any org's audit CSV (`admin_router.py:205`). Is a superadmin cross-tenant audit capability intended for a multi-tenant SaaS?
9. `POST /mcp/start_pipeline` and `POST /marketplace/install/{id}` (through `pipeline_service`) both bypass the trial, storage and prompt-guard gates in `/factory/start`. Is that intended?
