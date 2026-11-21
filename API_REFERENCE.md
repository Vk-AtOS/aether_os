# AetherOS API Reference

This file is generated from the live FastAPI app, not written by hand.

- Route list last synchronised on 17 Nov 2026 (r4/a_docs2, based on r3/int `88659af`). `scripts/ci/check_docs.py` (CI step "Docs match code") fails when a row here is not a live route, when a live route has no row, or when a summary is empty.
- Summaries are the handler docstring. Where a handler has none, the text is derived from the handler name and path (for the generic `/hr/<AGENT>/<method>` proxy routes, from the agent and method name). Treat those as labels, not specifications.
- Method: import `aether_os.gateway.api.app` and walk `app.routes` (every `APIRoute`).
- Counts: 658 route objects, 666 method+path pairs. `app.openapi()` lists 587 paths and 649 operations; the rest are hidden from the schema (`include_in_schema=False`) and are marked "hidden from OpenAPI" in the Summary column.
- The tables list routes only. Request and response bodies are not generated here. Read the handler, or run the app and open `/docs` (disabled when `ENVIRONMENT=production`, `gateway/api.py:107-108`).
- The "Auth" column is derived from the dependency tree of each route plus a text scan of the handler. It is a guide, not a proof. Treat the handler as the source of truth.
- To regenerate, run a script that imports the app and prints one table per router module. The script used for this file is a throw-away and is not kept in the repo. Regenerate it after route changes; a stale table is wrong.

## Conventions (checked against the code)

**Base URL.** `https://<your-domain>/`. A leading `/api` is stripped by a middleware, so `/api/auth/login` and `/auth/login` are the same route (`gateway/api.py:111-119`). The routes below are listed without `/api`.

**Content type.** JSON bodies. SSE streams use `text/event-stream`.

**Bearer token.** Protected routes need `Authorization: Bearer <token>`. The token is either a JWT or an API key that starts with `aesk_` (`gateway/dependencies.py:41-107`, `gateway/auth.py:157-158`). API keys act with role `api`, rank 1, the same rank as `member` (`core/policy/rules.py:22`).

**Access and refresh tokens.** The access token lives 1 hour, the refresh token 30 days (`gateway/auth.py:178,186`). A refresh token is single use: `POST /auth/refresh` spends it and returns a new pair (`gateway/routers/auth_refresh_router.py`). Logout revokes the session and the refresh family (`gateway/routers/auth_router.py`, `logout`).

**Roles.** From lowest to highest: `viewer`, `member`/`api`, `admin`, `owner`, `superadmin` (`core/policy/rules.py:22`). `get_current_user` reads the role from the database on every request, not from the token (`gateway/dependencies.py:94-97`).

**Role floor, applied centrally** (`gateway/role_gate.py`, called from `get_current_user`):
- Safe methods (GET, HEAD, OPTIONS) pass for every role.
- A `viewer` may not use POST, PUT, PATCH or DELETE, except the paths in `VIEWER_MAY` (own session, preferences, notifications, `/memory/search`, `/prime/`, `/chat/`, `/mail/`, `/hr/`, `/velaris/`, `/control/`, and a few others) and the exact paths in `POLICY_GATED`.
- `POLICY_GATED` routes are decided by the policy engine inside the handler. In the tables they show "policy engine decides".
- `/webhooks` and `/marketplace/publish` need `admin` or higher for any mutating method.
- Handlers may ask for more than the floor (owner, superadmin, a policy action). The "handler calls" and "handler checks role inline" notes in the Auth column point at those.

**Other checks in `get_current_user`.** 401 for a missing or revoked token, a deleted user or an inactive user. 403 `email_not_verified` when the email is not verified. 403 `password_change_required` on every route except `/auth/change-password` and `/auth/logout` when the user must rotate the password. 403 for a deleted organisation. A pending-MFA token (`mfa_pending`) is rejected with 401 (`gateway/dependencies.py:41-90`).

**Admin MFA.** If the organisation sets `require_admin_mfa` and the grace period is over, an owner or admin without MFA gets 403 with `{"error": "mfa_required", ...}` on every route except `/auth/mfa/*`, `/auth/logout`, `/auth/my-orgs` and `/account/settings` (`gateway/role_gate.py:83-101`).

### Auth flow

1. `POST /auth/register` with `email`, `password`, optional `name` and `org_name`, and both `terms_accepted: true` and `dpa_accepted: true`. Unknown fields are rejected (`extra = forbid`). The new user is `owner` and the plan is `trial`, whatever the body says. Errors: 422 `terms_and_dpa_required`, 422 for a password the safety check refuses, 400 `Email already registered`, 429 too many registrations (`gateway/routers/auth_router.py`).
2. `POST /auth/login` with `email` and `password`. Success returns `access_token`, `refresh_token`, `token_type`, `org_slug`, `org_id`, `plan`. Wrong credentials give 401 `Invalid credentials`. A disabled account gives 403.
3. If MFA is on, login returns `mfa_required: true` and an `mfa_token` and no access token. Send `mfa_token` and `code` to `POST /auth/mfa/confirm` to get the tokens. MFA confirm is limited to 5 attempts per 5 minutes per IP and per user (`gateway/auth_mfa.py:46`).
4. `POST /auth/refresh` with `refresh_token`. No bearer header is needed.
5. `POST /auth/logout` with the bearer token.

### Run event streams (SSE)

Browsers cannot send a bearer header on `EventSource`, so the stream uses a one-time token:
1. `POST /factory/runs/{run_id}/sse-token` (bearer auth). The response is `{"sse_token": "..."}`.
2. `GET /factory/runs/{run_id}/stream?sse_token=<token>`.

The SSE token is valid 30 seconds and can be used once (`gateway/auth_refresh.py:209-236`, `gateway/routers/factory_run_streaming_router.py:36-81`).

### Errors

Errors are JSON with a `detail` field (`gateway/api.py:196-215`):
- 422 validation errors: `{"detail": [<pydantic errors>], "body": "<first 200 chars of the body>"}`.
- 500: `{"detail": "An internal error occurred. The error has been logged."}`.
- Most handlers raise `HTTPException`, so `detail` is a string. A few use a dict, for example the admin MFA 403 above.
- SCIM routes return `application/scim+json` errors (`gateway/scim_patch.py`).

Common statuses: 401 missing, invalid or revoked token. 403 role too low, policy denial, unverified email. 404 not found, including a run that belongs to another organisation. 429 rate limit. 503 when the rate-limit or token-revocation store cannot answer in production.

### Pagination

There is no single scheme. Examples checked in the code:
- `GET /factory/runs`: `page` (default 1), `limit` (default 50, clamped to 1-100) and `cursor` (a float timestamp). The response has `items`, `page`, `limit`, `total`, `next_cursor`. When `cursor` is given, `page` is ignored (`gateway/routers/factory_runs_router.py:102-149`).
- `GET /auth/api-keys` and `GET /factory/decisions` use `limit` and `offset` with caps (`gateway/routers/auth_keys_router.py:103`, `gateway/routers/factory_decisions_router.py:27-28`).
- Admin and compliance lists use `page` and `limit` (`gateway/routers/admin_router.py:57-58`, `gateway/routers/compliance_router.py:54-55`).

Check the handler signature for each list route.

### Rate limits

| Limit | Value | Where |
|---|---|---|
| Per user, all authenticated routes | 600 per 60 s, env `API_RATE_PER_USER_PER_MIN` | `core/api_rate_limit.py:30-33` |
| Per organisation, all authenticated routes | 6000 per 60 s, env `API_RATE_PER_ORG_PER_MIN` | `core/api_rate_limit.py:30-33` |
| Login | 5 attempts per 15 min per IP, env `MAX_LOGIN_ATTEMPTS_PER_IP` | `core/rate_limiter.py:164,276-290` |
| Registration | 5 per hour per IP, env `MAX_REGISTRATIONS_PER_IP` | `core/rate_limiter.py:165,321-340` |
| Password reset | 5 per 15 min per IP, env `MAX_PASSWORD_RESET_PER_IP` | `core/rate_limiter.py:365-366` |
| Pipeline starts | 5 concurrent runs per org (`MAX_CONCURRENT_RUNS_PER_ORG`), 20 starts per org per hour (`MAX_STARTS_PER_ORG_PER_HOUR`), 10 factory starts per minute (`MAX_FACTORY_STARTS_PER_MIN`) | `core/rate_limiter.py:162-166` |

Over the API limit returns 429 with `Retry-After: 60`. If the shared store is down in production the request gets 503 with `Retry-After: 5` (`core/api_rate_limit.py:55-69`). Plan entitlements (runs per period, concurrent runs, seats) are enforced by the policy engine and are separate from these limits.

### Auth column legend

| Entry | Meaning |
|---|---|
| `get_current_user` | Valid JWT or API key. `floor:` is the role floor from `gateway/role_gate.py` for that method and path. |
| `require_run_user` | `get_current_user` plus a check that `{run_id}` belongs to the caller's organisation (`gateway/dependencies.py:168-174`). |
| `_require_plugin_admin` | `get_current_user` plus the `plugin.manage` policy action (`gateway/routers/plugins_router.py:43-46`). |
| `_admin` | A router-local admin check (owner or admin). |
| `_verify_scim_auth` | SCIM provisioning bearer token, not a user JWT (`gateway/routers/scim_router.py:66`). |
| `_portal_auth` | Client-portal token. |
| `require_ci_auth` | `CI_WEBHOOK_SECRET` via HMAC or `X-Gitlab-Token`; 503 when unset (`gateway/security.py:48-60`). |
| no auth dependency | Public, or the handler does its own check. The note in brackets says what the scan found. |
| handler calls `x` | The handler body calls a helper such as `_require_admin`, `enforce` or `admit_run_start`. |

## Routes

<!-- GENERATED: r3/int 88659af; 658 APIRoute objects; 666 method+path pairs; 587 OpenAPI paths; 649 OpenAPI operations; 57 pairs with 'no auth dependency' -->

### `gateway/auth_mfa.py`

Tags: mfa. Routes: 4.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/auth/mfa/confirm` | no auth dependency | Exchange a short-lived mfa_token + TOTP code for a full JWT. |
| POST | `/auth/mfa/disable` | `get_current_user`; floor: any role | Verify current TOTP code then disable MFA on the account. |
| POST | `/auth/mfa/setup` | `get_current_user`; floor: any role | Generate a new TOTP secret and store it (not yet enabled until verified). |
| POST | `/auth/mfa/verify-setup` | `get_current_user`; floor: any role | Confirm the TOTP code and activate MFA on the account. |

### `gateway/auth_oauth.py`

Tags: oauth. Routes: 5.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/auth/oauth/github` | no auth dependency | Github login. |
| GET | `/auth/oauth/github/callback` | no auth dependency | Github callback. (hidden from OpenAPI) |
| GET | `/auth/oauth/google` | no auth dependency | Google login. |
| GET | `/auth/oauth/google/callback` | no auth dependency | Google callback. (hidden from OpenAPI) |
| POST | `/auth/oauth/exchange` | no auth dependency | Trade the one-time code from the callback redirect for the session (or MFA challenge). Single use, 60 s. |

### `gateway/auth_saml.py`

Tags: saml. Routes: 4.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/auth/saml/available` | no auth dependency | Whether SSO sign-in can be offered. Public on purpose: the sign-in page |
| POST | `/auth/saml/callback` | no auth dependency | Process IdP response, create/update user, redirect to frontend with JWT. |
| GET | `/auth/saml/login` | no auth dependency | Redirect browser to the IdP SSO URL for the given org (or global fallback). |
| GET | `/auth/saml/metadata` | no auth dependency | Return SP metadata XML using the global SP config. |

### `gateway/client_portal/routes.py`

Tags: client-portal. Routes: 6.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/portal/{project_id}/approve` | `_portal_auth` | Record the client's sign-off (or change request) for this project. |
| POST | `/portal/{project_id}/feedback` | `_portal_auth` | Submit feedback. |
| GET | `/portal/{project_id}/phase/{phase_name}` | `_portal_auth` | Get phase output. |
| GET | `/portal/{project_id}/status` | `_portal_auth` | Get project status. |
| GET | `/portal/{run_id}/download` | `_portal_auth` | Download all project artifacts as a ZIP file (portal token or owning-org user). |
| GET | `/portal/{run_id}/provenance` | `_portal_auth` | Return the build provenance Markdown document. |

### `gateway/mcp_router.py`

Tags: MCP. Routes: 5.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/mcp/get_architecture/{run_id}` | `require_run_user`, `get_current_user`; floor: any role | Retrieve the architecture document for a run. |
| GET | `/mcp/get_artifact/{run_id}` | `require_run_user`, `get_current_user`; floor: any role | Retrieve a generated artifact file for a run (file_path query param). |
| GET | `/mcp/get_run_status/{run_id}` | `require_run_user`, `get_current_user`; floor: any role | Get phase-by-phase status of a run. |
| GET | `/mcp/list_runs` | `get_current_user`; floor: any role | List all factory runs for the authenticated org. |
| POST | `/mcp/start_pipeline` | `get_current_user`; floor: policy engine decides; handler calls `admit_run_start` | Start a new factory pipeline run. |

### `gateway/routers/account_codebase_router.py`

Tags: account. Routes: 2.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/account/codebase-profiles` | `get_current_user`; floor: any role | Return all imported codebase profiles for the current org. |
| POST | `/account/import-codebase` | `get_current_user`; floor: any role | Fetch a public GitHub repo's file tree, detect its stack, and store a CodebaseProfile. |

### `gateway/routers/account_router.py`

Tags: account. Routes: 8.

| Method | Path | Auth | Summary |
|---|---|---|---|
| DELETE | `/account` | `get_current_user`; floor: any role | GDPR erasure: anonymise and soft-delete the calling user's account. |
| GET | `/account/data-export` | `get_current_user`; floor: any role | GDPR portability: return all user data as a downloadable JSON file. |
| GET | `/account/preferences` | `get_current_user`; floor: any role | Get user preferences. |
| PUT | `/account/preferences` | `get_current_user`; floor: any role | Update user preferences. |
| GET | `/account/projects` | `get_current_user`; floor: any role | List all generated projects for the org. |
| GET | `/account/projects/search` | `get_current_user`; floor: any role | Search projects by name or requirement text. |
| GET | `/account/storage` | `get_current_user`; floor: any role | Get account storage. |
| GET | `/account/usage` | `get_current_user`; floor: any role | Get current usage and limits for the organisation. |

### `gateway/routers/account_settings_router.py`

Tags: account. Routes: 4.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/account/settings` | `get_current_user`; floor: any role | Return org-level settings (autonomous_mode, data_region, etc.). |
| POST | `/account/settings` | `get_current_user`; floor: any role; handler checks role inline | Update account settings (e.g. decision_mode, autonomous_mode). |
| DELETE | `/org` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Delete the current organisation (owner only). This cannot be undone: users are anonymised, passwords |
| GET | `/orgs/me/usage` | `get_current_user`; floor: any role | Return current org usage stats for billing and settings panels. |

### `gateway/routers/admin_platform_router.py`

Tags: admin. Routes: 5.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/admin/kill-all` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Kill all. |
| GET | `/admin/platform-health` | `get_current_user`; floor: any role; handler checks role inline | Platform health. |
| POST | `/admin/platform/save-file` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Apply a code fix to a platform-level monitored file (P9). |
| POST | `/admin/prune-artifacts` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Delete artifact files older than `ttl_days` (default 30). Superadmin only. |
| POST | `/admin/system/deploy` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Pull latest code from git and restart the service. |

### `gateway/routers/admin_quality_router.py`

Tags: admin. Routes: 3.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/admin/platform/phase-latency` | `get_current_user`; floor: any role; handler checks role inline | Return per-phase latency data.  Uses the phase_completions table which stores |
| GET | `/admin/platform/quality-metrics` | `get_current_user`; floor: any role; handler checks role inline | Return a JSON dashboard of pipeline quality. |
| GET | `/admin/platform/run-costs` | `get_current_user`; floor: any role; handler checks role inline | Return cost data from LLMCallRecord rows.  If token usage has been tracked |

### `gateway/routers/admin_router.py`

Tags: admin. Routes: 10.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/admin/audit/export.csv` | `get_current_user`; floor: any role; handler checks role inline | Export AuditLog rows as a streaming CSV download. Admin/owner only. |
| GET | `/admin/error-registry` | `get_current_user`; floor: any role; handler calls `_require_registry`; handler checks role inline | Return all entries from the error registry. Platform operator (superadmin) only: the registry is platform-wide, not per organisation. |
| GET | `/admin/error-registry/summary` | `get_current_user`; floor: any role; handler calls `_require_registry`; handler checks role inline | Return per-category counts, last-seen dates, and fix status. Platform operator (superadmin) only: the registry is platform-wide, not per organisation. |
| POST | `/admin/error-registry/{category}/mark-fixed` | `get_current_user`; floor: member+ (viewer denied); handler calls `_require_registry`; handler checks role inline | Record a fix for a given error category. Superadmin only. |
| GET | `/admin/users` | `get_current_user`; floor: any role; handler checks role inline | List users. |
| POST | `/admin/users/invite` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Invite user. |
| POST | `/admin/users/{user_id}/deactivate` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Deactivate user. |
| POST | `/admin/users/{user_id}/reactivate` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Reactivate user. |
| POST | `/admin/users/{user_id}/reset-password` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Reset a user's password to a temporary value.  Admin/owner only. |
| POST | `/admin/users/{user_id}/role` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Update user role. |

### `gateway/routers/agents_router.py`

Tags: agents. Routes: 2.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/agents` | `get_current_user`; floor: any role | List all registered agents with their name, kind, and availability. |
| POST | `/agents/{agent_name}/run` | `get_current_user`; floor: policy engine decides; handler calls `enforce`; handler checks role inline | Run a specific agent with the provided metadata context. |

### `gateway/routers/app_preview_router.py`

Tags: app-preview. Routes: 10.

| Method | Path | Auth | Summary |
|---|---|---|---|
| DELETE | `/app-preview` | no auth dependency | Public on purpose: returns no data. Generated apps live on per-run origins (hidden from OpenAPI) |
| GET | `/app-preview` | no auth dependency | Public on purpose: returns no data. Generated apps live on per-run origins (hidden from OpenAPI) |
| HEAD | `/app-preview` | no auth dependency | Public on purpose: returns no data. Generated apps live on per-run origins (hidden from OpenAPI) |
| PATCH | `/app-preview` | no auth dependency | Public on purpose: returns no data. Generated apps live on per-run origins (hidden from OpenAPI) |
| POST | `/app-preview` | no auth dependency | Public on purpose: returns no data. Generated apps live on per-run origins (hidden from OpenAPI) |
| PUT | `/app-preview` | no auth dependency | Public on purpose: returns no data. Generated apps live on per-run origins (hidden from OpenAPI) |
| DELETE | `/app-preview/{path:path}` | no auth dependency | Public on purpose: returns no data. Generated apps live on per-run origins (hidden from OpenAPI) |
| GET | `/app-preview/{path:path}` | no auth dependency | Public on purpose: returns no data. Generated apps live on per-run origins (hidden from OpenAPI) |
| HEAD | `/app-preview/{path:path}` | no auth dependency | Public on purpose: returns no data. Generated apps live on per-run origins (hidden from OpenAPI) |
| PATCH | `/app-preview/{path:path}` | no auth dependency | Public on purpose: returns no data. Generated apps live on per-run origins (hidden from OpenAPI) |
| POST | `/app-preview/{path:path}` | no auth dependency | Public on purpose: returns no data. Generated apps live on per-run origins (hidden from OpenAPI) |
| PUT | `/app-preview/{path:path}` | no auth dependency | Public on purpose: returns no data. Generated apps live on per-run origins (hidden from OpenAPI) |

### `gateway/routers/auth_keys_router.py`

Tags: auth. Routes: 6.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/auth/api-keys` | `get_current_user`; floor: any role; handler calls `enforce` | Active API keys of the current organisation, newest first (never the secret). |
| POST | `/auth/api-keys` | `get_current_user`; floor: member+ (viewer denied); handler calls `enforce` | Create a new API key for the current organisation (owner/admin; a key cannot mint keys). |
| DELETE | `/auth/api-keys/{key_id}` | `get_current_user`; floor: member+ (viewer denied); handler calls `enforce` | Revoke an API key by ID. |
| GET | `/auth/mfa/status` | `get_current_user`; floor: any role | Return whether MFA is enabled for the current user. |
| GET | `/auth/my-orgs` | `get_current_user`; floor: any role | Return all organisations the current user belongs to. |
| POST | `/auth/switch-org` | `get_current_user`; floor: member+ (viewer denied) | Switch the authenticated user's active organisation and issue new tokens. |

### `gateway/routers/auth_password_router.py`

Tags: auth. Routes: 4.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/auth/change-password` | `get_current_user`; floor: any role | Change the authenticated user's password with HIBP breach check. |
| POST | `/auth/password-reset-confirm` | no auth dependency | Confirm password reset using the token. |
| POST | `/auth/password-reset-request` | no auth dependency | Request a password reset email. |
| GET | `/auth/verify-email` | no auth dependency | Verify user's email address using the token. |

### `gateway/routers/auth_refresh_router.py`

Tags: auth. Routes: 1.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/auth/refresh` | no auth dependency | Exchange a refresh token for a new access + refresh pair (single use). |

### `gateway/routers/auth_router.py`

Tags: auth. Routes: 3.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/auth/login` | no auth dependency | Authenticate and return a JWT token. |
| POST | `/auth/logout` | `get_current_user`; floor: any role | Blacklist this access token and revoke the refresh-token family issued with it. |
| POST | `/auth/register` | no auth dependency | Register a new organisation and owner user. |

### `gateway/routers/billing_router.py`

Tags: billing. Routes: 8.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/billing/cancel` | `get_current_user`; floor: policy engine decides; handler calls `_require_billing_admin` | Cancel the paid plan: same path as a downgrade to free (provider first, then the org). |
| POST | `/billing/create-order` | `get_current_user`; floor: policy engine decides; handler calls `_require_billing_admin` | Create a Razorpay order for a plan upgrade. |
| POST | `/billing/downgrade` | `get_current_user`; floor: policy engine decides; handler calls `_require_billing_admin` | Move the org to a lower plan now (owner/admin). A lower paid plan keeps the paid period; free/trial end it. |
| GET | `/billing/invoices` | `get_current_user`; floor: any role | Return invoices for the authenticated org. |
| GET | `/billing/plans` | no auth dependency | Return available subscription plans (public endpoint). |
| GET | `/billing/status` | `get_current_user`; floor: any role | The org's plan in force and when its paid period ends (unix seconds, or null). |
| POST | `/billing/verify-payment` | `get_current_user`; floor: policy engine decides; handler calls `_require_billing_admin` | Verify Razorpay payment signature and upgrade org plan. |
| POST | `/billing/webhook` | no auth dependency | Handle Razorpay webhook events (payment.captured, subscription events). |

### `gateway/routers/billing_stripe_router.py`

Tags: billing. Routes: 3.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/billing/stripe/checkout` | `get_current_user`; floor: policy engine decides; handler calls `enforce` | Create a Stripe Checkout Session for a plan upgrade. |
| GET | `/billing/stripe/portal` | `get_current_user`; floor: any role; handler calls `enforce` | Create a Stripe Customer Portal session for managing the subscription. |
| POST | `/billing/stripe/webhook` | no auth dependency | Handle Stripe webhook events (public: Stripe calls it; the stripe-signature |

### `gateway/routers/clarifying_router.py`

Tags: runs. Routes: 2.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/factory/runs/{run_id}/clarifying-answers` | `require_run_user`, `get_current_user`; floor: any role | Get clarifying answers. |
| POST | `/factory/runs/{run_id}/clarifying-answers` | `require_run_user`, `get_current_user`; floor: policy engine decides; handler calls `enforce` | Submit clarifying answers. |

### `gateway/routers/compliance_router.py`

Tags: audit, compliance. Routes: 5.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/audit/logs` | `get_current_user`; floor: any role; handler checks role inline | Get audit logs. |
| GET | `/audit/logs/export` | `get_current_user`; floor: any role; handler checks role inline | T4-09: Export audit logs as JSON or CSV. Retention window controlled by `days`. |
| DELETE | `/audit/logs/purge` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Refused: the audit ledger is append-only (no update or delete paths). |
| GET | `/compliance/artifacts/{run_id}` | `require_run_user`, `get_current_user`; floor: any role | Return a ZIP containing the compliance JSON + PDF for a given run. |
| GET | `/compliance/org-report` | `get_current_user`; floor: any role | Get compliance report. |

### `gateway/routers/factory_analytics_router.py`

Tags: factory. Routes: 4.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/analytics/quality-trend` | `get_current_user`; floor: any role | Return daily quality metrics for the last N days. |
| GET | `/factory/analytics/quality-trend` | `get_current_user`; floor: any role | Return quality + compliance scores for recent completed runs - proves cross-run improvement. |
| GET | `/factory/deployments` | `get_current_user`; floor: any role | List deployments: completed runs from DB plus running Docker containers. |
| GET | `/factory/search` | `get_current_user`; floor: any role | Semantic search across all generated artifacts for the organisation. |

### `gateway/routers/factory_decisions_router.py`

Tags: decisions. Routes: 1.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/factory/decisions` | `get_current_user`; floor: any role | Decisions of the caller's organisation only (org comes from the token, never the request). |

### `gateway/routers/factory_intake_router.py`

Tags: factory. Routes: 4.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/factory/fetch-github-repo` | `get_current_user`; floor: member+ (viewer denied) | Fetch key files from a GitHub repo to use as codebase context. |
| POST | `/factory/fetch-repo` | `get_current_user`; floor: member+ (viewer denied) | Fetch codebase context from GitHub, GitLab, or an SSH-accessible repository. |
| POST | `/factory/import-schema` | `get_current_user`; floor: member+ (viewer denied) | Import schema from an existing database to use as p02 architecture input. |
| POST | `/factory/upload-requirement` | `get_current_user`; floor: member+ (viewer denied) | Parse an uploaded file (PDF/MD/TXT/image) and return extracted requirement text. |

### `gateway/routers/factory_ops_router.py`

Tags: factory. Routes: 3.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/pipeline/approve/{ticket_id}` | `get_current_user`; floor: member+ (viewer denied) | Approve or deny a human-gated pipeline action via DecisionEngine. |
| GET | `/pipeline/status/{run_id}` | `get_current_user`; floor: any role | Get status of a pipeline run. |
| GET | `/templates` | `get_current_user`; floor: any role | Return available project templates. |

### `gateway/routers/factory_run_compliance_router.py`

Tags: run-compliance. Routes: 3.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/factory/runs/{run_id}/compliance` | `require_run_user`, `get_current_user`; floor: any role | Return the compliance scan result for a pipeline run. |
| GET | `/factory/runs/{run_id}/decisions` | `require_run_user`, `get_current_user`; floor: any role | List decisions (spec approvals, phase gates) for a run. |
| GET | `/factory/runs/{run_id}/portal` | `get_current_user`; floor: any role | Return portal HTML content path and run summary. |

### `gateway/routers/factory_run_files_router.py`

Tags: run-files. Routes: 9.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/factory/runs/{run_id}/envvars` | `get_current_user`; floor: any role | Read the .env (or .env.example) file from the project root. |
| PATCH | `/factory/runs/{run_id}/envvars` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Write a .env file in the project root from the given key-value pairs. |
| GET | `/factory/runs/{run_id}/file-content` | `get_current_user`; floor: any role | Read file content from the run's project directory. |
| PATCH | `/factory/runs/{run_id}/file-content` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Write content to a file in the project directory. |
| GET | `/factory/runs/{run_id}/files` | `get_current_user`; floor: any role | Recursive file tree for a run's output directory. |
| POST | `/factory/runs/{run_id}/memory/changelog` | `get_current_user`; floor: member+ (viewer denied); handler calls `enforce` | Add entry to project changelog (member or above). |
| POST | `/factory/runs/{run_id}/open-in-vscode` | `get_current_user`; floor: member+ (viewer denied) | Open the project folder in VS Code on the local machine. |
| GET | `/factory/runs/{run_id}/snapshots` | `get_current_user`; floor: any role | List all code snapshots for a run (versioned file history). |
| GET | `/factory/runs/{run_id}/snapshots/{snapshot_id}` | `get_current_user`; floor: any role | Get full content of a specific code snapshot. |
| POST | `/factory/runs/{run_id}/snapshots/{snapshot_id}/rollback` | `get_current_user`; owner or admin only | Restore the file a snapshot was taken from (org-scoped, audited as `run.rollback`). |

### `gateway/routers/factory_run_streaming_router.py`

Tags: run-streaming. Routes: 2.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/factory/runs/{run_id}/sse-token` | `require_run_user`, `get_current_user`; floor: any role | Exchange bearer JWT for a short-lived (30s) SSE-only token for this run. |
| GET | `/factory/runs/{run_id}/stream` | no auth dependency | Server-Sent Events stream for live pipeline output. |

### `gateway/routers/factory_runs_router.py`

Tags: runs. Routes: 6.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/factory/runs` | `get_current_user`; floor: any role | List pipeline runs for the organisation with cursor-based pagination. |
| GET | `/factory/runs/{run_id}` | `get_current_user`; floor: any role | Get detail for a single pipeline run. |
| GET | `/factory/runs/{run_id}/events` | `get_current_user`; floor: any role | Return all pipeline events for a run, ordered by created_at. |
| POST | `/factory/runs/{run_id}/priority` | `get_current_user`; floor: member+ (viewer denied) | Set the priority label for a run. |
| GET | `/factory/runs/{run_id}/quality` | `get_current_user`; floor: any role | Get quality score for a completed run's generated output. |
| GET | `/factory/runs/{run_id}/test-report` | `require_run_user`, `get_current_user`; floor: any role | The self-test report for a run: the stored one, else the unit-test phase's summary. |

### `gateway/routers/factory_start_router.py`

Tags: factory. Routes: 2.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/factory/estimate` | `get_current_user`; floor: any role | Estimate monthly hosting cost based on tech stack and domain. |
| POST | `/factory/start` | `get_current_user`; floor: policy engine decides; handler calls `admit_run_start`, `enforce` | Start a new factory pipeline run (10-phase path). |

### `gateway/routers/guardian_router.py`

Tags: Guardian. Routes: 4.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/guardian/events` | `get_current_user`; floor: any role; handler calls `_require_admin`; handler checks role inline | List events. |
| POST | `/guardian/scan` | `get_current_user`; floor: member+ (viewer denied) | FE-H1: Trigger a Guardian threat scan for the caller's org. |
| GET | `/guardian/stats` | `get_current_user`; floor: any role; handler checks role inline | Cumulative prevention counters - powers the real-time threat dashboard. |
| GET | `/guardian/status` | no auth dependency (handler reads the bearer token itself); handler checks role inline | Current threat level, last snapshot, and live service health. |

### `gateway/routers/guardian_snapshots_router.py`

Tags: Guardian. Routes: 5.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/guardian/events/{event_id}/resolve` | `get_current_user`; floor: member+ (viewer denied); handler calls `_require_admin`; handler checks role inline | Resolve event. |
| POST | `/guardian/restore/{snapshot_id}` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Restore the platform database from a snapshot. Superadmin only. |
| GET | `/guardian/snapshots` | `get_current_user`; floor: any role; handler checks role inline | List available database snapshots. Platform-level, so restricted to superadmins. |
| POST | `/guardian/snapshots` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Trigger a manual database snapshot. Superadmin only. |
| POST | `/guardian/update-baseline` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Refresh the file integrity baseline for specific files. |

### `gateway/routers/health_router.py`

Tags: health. Routes: 9.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/` | no auth dependency | Serve the public landing page. |
| GET | `/api/health` | no auth dependency | Health check endpoint. |
| GET | `/api/health/zero-trust` | no auth dependency | Zero-trust subsystem health check. |
| GET | `/favicon.ico` | no auth dependency | Serve the AetherOS favicon. (hidden from OpenAPI) |
| GET | `/favicon.svg` | no auth dependency | Serve the AetherOS favicon. (hidden from OpenAPI) |
| GET | `/health` | no auth dependency | Health check endpoint. |
| GET | `/health/zero-trust` | no auth dependency | Zero-trust subsystem health check. |
| GET | `/healthz` | no auth dependency | Liveness: the process is up and its event loop answers. Touches no dependency, so a Postgres or Redis outage |
| GET | `/readyz` | no auth dependency | Readiness: 200 when this instance can serve traffic, 503 when it cannot (load balancers stop routing to it). |

### `gateway/routers/intelligence_router.py`

Tags: intelligence. Routes: 14.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/intelligence/arch-governor/review` | `get_current_user`; floor: member+ (viewer denied); handler calls `assert_run_in_org`, `enforce` | T9-01: Review generated code against architecture spec. |
| POST | `/intelligence/conflict-resolver/detect` | `get_current_user`; floor: member+ (viewer denied) | T9-03: Detect conflicts in requirements or architecture. |
| POST | `/intelligence/conflict-resolver/resolve` | `get_current_user`; floor: member+ (viewer denied); handler calls `assert_run_in_org` | T9-03: Record a conflict resolution. |
| GET | `/intelligence/conflict-resolver/resolved` | `get_current_user`; floor: any role; scoped to the caller's `org_id` | Conflicts already resolved in the caller's organisation, with who resolved them (KAN-154). |
| GET | `/intelligence/global-insights` | `get_current_user`; floor: any role | Authenticated intelligence feed - aggregated from GlobalPattern + completed runs. |
| GET | `/intelligence/global-patterns` | `get_current_user`; floor: any role | Return all learned GlobalPattern entries for the platform. |
| POST | `/intelligence/global-patterns` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Admin: create a GlobalPattern override to manually tune learned behaviors. |
| DELETE | `/intelligence/global-patterns/{pattern_id}` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Admin: delete a GlobalPattern entry to remove incorrect learned behaviors. |
| PUT | `/intelligence/global-patterns/{pattern_id}` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Admin: update a GlobalPattern to correct learned behavior. |
| POST | `/intelligence/improvement-loop/cycle` | `require_run_user`, `get_current_user`; floor: member+ (viewer denied) | T9-05: Run a full improvement loop cycle for a completed run. |
| GET | `/intelligence/maintenance-engine/health/{run_id}` | `require_run_user`, `get_current_user`; floor: any role | T9-06: Health check for a project run. |
| POST | `/intelligence/maintenance-engine/scan` | `get_current_user`; floor: member+ (viewer denied); handler calls `assert_run_in_org` | T9-06: Scan dependencies and/or analyze tech debt. |
| GET | `/intelligence/quality-benchmark` | `get_current_user`; floor: any role | Quality benchmark aggregated from real completed run data. |
| POST | `/intelligence/tradeoff-engine/analyze` | `get_current_user`; floor: member+ (viewer denied) | T9-04: Analyze architectural tradeoffs between two options. |
| POST | `/intelligence/truth-engine/validate` | `get_current_user`; floor: member+ (viewer denied); handler calls `assert_run_in_org` | T9-02: Validate requirements coverage in generated output. |

### `gateway/routers/learning_router.py`

Tags: learning. Routes: 6.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/factory/runs/{run_id}/feedback` | `require_run_user`, `get_current_user`; floor: member+ (viewer denied) | Submit star rating + optional tags/comment for a completed run. |
| GET | `/learning/clarifications` | `get_current_user`; floor: any role | Return pending project-scoped clarification questions for the current user. |
| POST | `/learning/clarifications/{clarification_id}/answer` | `get_current_user`; floor: member+ (viewer denied) | Submit an answer to a pending clarification question. |
| GET | `/learning/context` | `get_current_user`; floor: any role | Return learned patterns for the current user (used by pipeline for LLM personalisation). |
| GET | `/learning/golden-builds` | `get_current_user`; floor: any role | List active golden build examples. |
| GET | `/learning/stats` | `get_current_user`; floor: any role | Return self-improvement system statistics. |

### `gateway/routers/ledger_anchor_router.py`

Tags: ledger. Routes: 6.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/prime/ledger/anchor` | `get_current_user`; floor: any role; handler calls `_admin` | Verify the organisation's chain and sign its current head now. |
| POST | `/prime/ledger/anchor/check-file` | `get_current_user`; floor: any role; handler checks role inline | Superadmin: verify every chain against the local anchor file. |
| GET | `/prime/ledger/anchor/export` | `get_current_user`; floor: any role; handler calls `_admin` | Every signed checkpoint of the organisation's chain, the public key and the genesis |
| GET | `/prime/ledger/anchor/latest` | `get_current_user`; floor: any role; handler checks role inline | The newest signed checkpoint of the caller's organisation chain, and the key to check it. |
| POST | `/prime/ledger/anchor/verify` | `get_current_user`; floor: any role; handler calls `_admin` | Verify the organisation's chain against its signed checkpoints and, if given, a |
| POST | `/prime/ledger/subjects/erase` | `get_current_user`; floor: any role; handler calls `_admin`; handler checks role inline | Erase a person's email or IP from what the ledger reveals in one organisation. |

### `gateway/routers/ledger_ops_router.py`

Tags: ledger. Routes: 2.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/prime/ledger/backfill` | `get_current_user`; floor: any role; handler calls `_superadmin`; handler checks role inline | Import audit_log rows that never reached a chain. Dry run is the default; a real |
| POST | `/prime/ledger/erasure/retry` | `get_current_user`; floor: any role; handler calls `_superadmin`; handler checks role inline | Erase the ledger personal data of deleted organisations whose erasure did not |

### `gateway/routers/legal_router.py`

Tags: legal. Routes: 3.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/legal/dpa` | no auth dependency | Data Processing Agreement (GDPR Art. 28). |
| GET | `/legal/privacy` | no auth dependency | Privacy Policy. |
| GET | `/legal/tos` | no auth dependency | Terms of Service / EULA. |

### `gateway/routers/llm_controls_router.py`

Tags: llm-controls. Routes: 5.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/admin/llm/kill-switch` | `get_current_user`; floor: member+ (viewer denied); handler calls `_superadmin`; handler checks role inline | Global kill. |
| PUT | `/admin/llm/orgs/{org_id}/cap` | `get_current_user`; floor: member+ (viewer denied); handler calls `_superadmin`; handler checks role inline | Set org cap. |
| GET | `/admin/llm/status` | `get_current_user`; floor: any role; handler calls `_superadmin`; handler checks role inline | Status for `/admin/llm/status`. |
| PUT | `/settings/llm/cap` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Org admin sets the org's own lower-only cap (`llm_org_cap_usd`); effective cap is the minimum with the platform cap. |
| POST | `/settings/llm/kill-switch` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Org kill. |
| GET | `/settings/llm/usage` | `get_current_user`; floor: any role | Usage for `/settings/llm/usage`. |

### `gateway/routers/marketplace_router.py`

Tags: marketplace. Routes: 7.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/marketplace/install/{profile_id}` | `get_current_user`; floor: policy engine decides; handler calls `admit_run_start` | T5-02: Install a marketplace profile - increment usage_count and start a |
| GET | `/marketplace/installed` | `get_current_user`; floor: any role | FE-H2: Return the marketplace profiles installed for the caller's org. |
| GET | `/marketplace/profiles` | no auth dependency | List profiles. |
| DELETE | `/marketplace/profiles/{profile_id}` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Delete marketplace profile. |
| GET | `/marketplace/profiles/{profile_id}` | no auth dependency | Get marketplace profile. |
| PUT | `/marketplace/profiles/{profile_id}` | `get_current_user`; floor: member+ (viewer denied) | Update marketplace profile. |
| POST | `/marketplace/publish` | `get_current_user`; floor: admin+ | Publish profile. |

### `gateway/routers/memory_router.py`

Tags: memory. Routes: 2.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/memory/graph` | `get_current_user`; floor: any role | Return memory store data in graph format for visualisation (nodes + edges). |
| POST | `/memory/search` | `get_current_user`; floor: any role | Similarity search over past runs for the current org. |

### `gateway/routers/metrics_router.py`

Tags: metrics. Routes: 1.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/metrics` | no auth dependency | Prometheus metrics - protected by X-Metrics-Key header when METRICS_API_KEY is set. (hidden from OpenAPI) |

### `gateway/routers/notification_prefs_router.py`

Tags: notifications. Routes: 3.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/notifications/preferences` | `get_current_user`; floor: any role | Get preferences. |
| PUT | `/notifications/preferences` | `get_current_user`; floor: any role | Put preferences. |
| PUT | `/notifications/preferences/org` | `get_current_user`; floor: any role; handler checks role inline | Put org preferences. |
| GET | `/notifications/quiet-hours` | `get_current_user`; floor: any role | Get the caller's quiet hours and the organisation default. |
| PUT | `/notifications/quiet-hours` | `get_current_user`; floor: any role | Set the caller's quiet hours (IANA zone, may wrap midnight). |
| PUT | `/notifications/quiet-hours/org` | `get_current_user`; floor: any role; handler checks role inline | Set the organisation's default quiet hours (admin). |

### `gateway/routers/notifications_router.py`

Tags: notifications. Routes: 3.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/notifications` | `get_current_user`; floor: any role | Get notifications. |
| POST | `/notifications/read-all` | `get_current_user`; floor: any role | Mark all notifications read. |
| POST | `/notifications/{notif_id}/read` | `get_current_user`; floor: any role | Mark notification read. |

### `gateway/routers/onboarding_router.py`

Tags: onboarding. Routes: 2.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/onboarding` | `get_current_user`; floor: any role | Get onboarding. |
| POST | `/onboarding/dismiss` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Dismiss onboarding. |
| POST | `/onboarding/dpa` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Accept the DPA for the organisation (owner/admin; stored with user and time). |

### `gateway/routers/ops_status_router.py`

Tags: system. Routes: 2.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/system/components` | `_admin`, `get_current_user`; floor: any role | Components for `/system/components`. |
| GET | `/system/dead-letters` | `_admin`, `get_current_user`; floor: any role; handler checks role inline | The queue is platform-wide, so an organisation sees only the dead letters of its own runs. |

### `gateway/routers/plugins_connectors_router.py`

Tags: plugins. Routes: 9.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/v2/plugins/connectors/ldap/authenticate` | `_require_plugin_admin`, `get_current_user`; floor: policy engine decides | Authenticate a user against Active Directory / LDAP (a password oracle: 30 attempts per org per 10 minutes). |
| POST | `/v2/plugins/connectors/ldap/users` | `_require_plugin_admin`, `get_current_user`; floor: policy engine decides | Search for all user objects in the LDAP/AD directory. |
| POST | `/v2/plugins/connectors/ldap/validate` | `_require_plugin_admin`, `get_current_user`; floor: policy engine decides | Test LDAP/Active Directory connectivity by performing a service account bind. |
| POST | `/v2/plugins/connectors/salesforce/objects` | `_require_plugin_admin`, `get_current_user`; floor: member+ (viewer denied) | List all available SObjects in the Salesforce org. |
| POST | `/v2/plugins/connectors/salesforce/objects/{object_name}/describe` | `_require_plugin_admin`, `get_current_user`; floor: member+ (viewer denied) | Describe a Salesforce SObject - returns fields and metadata. |
| POST | `/v2/plugins/connectors/salesforce/query` | `_require_plugin_admin`, `get_current_user`; floor: policy engine decides | Execute a SOQL query against Salesforce. |
| POST | `/v2/plugins/connectors/salesforce/validate` | `_require_plugin_admin`, `get_current_user`; floor: policy engine decides | Validate Salesforce credentials by calling the REST API root endpoint. |
| GET | `/v2/plugins/skills` | `get_current_user`; floor: any role | List all available skills with their metadata. |
| POST | `/v2/plugins/skills/generate` | `get_current_user`; floor: member+ (viewer denied) | Generate code using a skill. |

### `gateway/routers/plugins_router.py`

Tags: plugins. Routes: 8.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/v2/plugins/catalog` | `get_current_user`; floor: any role | Browse all available plugins in the built-in catalog. |
| GET | `/v2/plugins/catalog/{plugin_id}` | `get_current_user`; floor: any role | Get full manifest for a specific plugin. |
| POST | `/v2/plugins/connectors/invoke` | `_require_plugin_admin`, `get_current_user`; floor: policy engine decides | Invoke a specific action on an installed connector. |
| POST | `/v2/plugins/install` | `_require_plugin_admin`, `get_current_user`; floor: policy engine decides | Install a plugin for this org with the given config. |
| GET | `/v2/plugins/installed` | `get_current_user`; floor: any role | List all plugins installed for this org. |
| DELETE | `/v2/plugins/installed/{plugin_id}` | `_require_plugin_admin`, `get_current_user`; floor: policy engine decides | Uninstall a plugin for this org. |
| PUT | `/v2/plugins/installed/{plugin_id}/config` | `_require_plugin_admin`, `get_current_user`; floor: policy engine decides | Update the config (credentials) for an installed plugin. |
| POST | `/v2/plugins/installed/{plugin_id}/test` | `_require_plugin_admin`, `get_current_user`; floor: policy engine decides | Test credentials for an installed plugin by making a real API call. |

### `gateway/routers/portal_admin_router.py`

Tags: client-portal-admin. Routes: 4.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/factory/runs/{run_id}/portal-approvals` | `require_run_user`, `get_current_user`; floor: any role; handler calls `enforce` | List portal approvals. |
| GET | `/factory/runs/{run_id}/portal-tokens` | `require_run_user`, `get_current_user`; floor: any role; handler calls `enforce` | List portal tokens. |
| POST | `/factory/runs/{run_id}/portal-tokens` | `require_run_user`, `get_current_user`; floor: policy engine decides; handler calls `enforce` | Issue a portal token for this run. The `token` field is returned here and never again. |
| DELETE | `/factory/runs/{run_id}/portal-tokens/{token_id}` | `require_run_user`, `get_current_user`; floor: policy engine decides; handler calls `enforce` | Revoke portal token. |

### `gateway/routers/preview_session_router.py`

Tags: runs. Routes: 1.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/factory/runs/{run_id}/preview-session` | `require_run_user`, `get_current_user`; floor: any role | Create preview session. |

### `gateway/routers/prime_corrections_router.py`

Tags: prime-corrections. Routes: 4.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/prime/corrections/eval-set` | `get_current_user`; floor: any role; handler checks role inline | Good examples as test cases: input, expected corrected output. Edits only (a rejection |
| POST | `/prime/corrections/outcome` | `get_current_user`; floor: any role | Say whether the retrieved corrections changed what the agent proposed. |
| GET | `/prime/corrections/relevant` | `get_current_user`; floor: any role | The corrections to show an agent before it proposes this action, and the prompt block. |
| PUT | `/prime/corrections/{correction_id}/good-example` | `get_current_user`; floor: any role; handler calls `_admin` | Mark good example. |

### `gateway/routers/prime_inbox_router.py`

Tags: prime. Routes: 8.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/prime/deputies` | `get_current_user`; floor: any role | Delegations the caller gave and those naming the caller as deputy, each with |
| GET | `/prime/inbox` | `get_current_user`; floor: any role | Requests waiting for the caller, as owner or as the active deputy of a delegation. |
| GET | `/prime/inbox/count` | `get_current_user`; floor: any role | Badge numbers for the dashboard: what the caller may decide now, and what lapses within 24h. |
| POST | `/prime/requests` | `get_current_user`; floor: any role | Ask Prime to carry out an action. Prime decides; a person may have to approve. |
| GET | `/prime/requests/{request_id}` | `get_current_user`; floor: any role | Get request. |
| POST | `/prime/requests/{request_id}/approve` | `get_current_user`; floor: any role | Approve exactly the request whose hash is quoted, then carry it out once. |
| POST | `/prime/requests/{request_id}/edit` | `get_current_user`; floor: any role | Change a pending request's amount or editable parameters. Makes a new revision with a new |
| POST | `/prime/requests/{request_id}/reject` | `get_current_user`; floor: any role | Reject request. |

### `gateway/routers/prime_ledger_router.py`

Tags: prime. Routes: 2.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/prime/ledger/entries` | `get_current_user`; floor: any role | List entries. |
| GET | `/prime/ledger/entries/{seq}` | `get_current_user`; floor: any role | One entry, the hash of the entry before it, and whether the link holds. |

### `gateway/routers/prime_router.py`

Tags: prime. Routes: 9.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/prime/activity` | `get_current_user`; floor: any role | Ledger entries about the caller's own delegations and Prime decisions, newest first. |
| POST | `/prime/check` | `get_current_user`; floor: any role | Ask Prime what it would do with this action on the caller's behalf. |
| GET | `/prime/delegations` | `get_current_user`; floor: any role | List delegations. |
| POST | `/prime/delegations` | `get_current_user`; floor: any role | Create delegation. |
| POST | `/prime/delegations/{delegation_id}/revoke` | `get_current_user`; floor: any role | Revoke delegation. |
| GET | `/prime/ledger/verify` | `get_current_user`; floor: any role; handler checks role inline | Verify the caller's own organisation chain (incrementally from its newest signed |
| GET | `/prime/limits` | `get_current_user`; floor: any role; handler checks role inline | This organisation's Prime limits and the bounds no setting can pass. |
| PUT | `/prime/limits` | `get_current_user`; floor: any role; handler checks role inline | Change the organisation's limits. Organisation admins only; ledgered. |
| GET | `/prime/meta` | `get_current_user`; floor: any role | What Prime can be asked to do, and what it never does. |

### `gateway/routers/prime_service_router.py`

Tags: prime-service. Routes: 2.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/prime/service/authorize-read` | `get_current_user`; floor: any role | {caller, category, subject_id, org} -> {allowed, reason}. |
| GET | `/prime/service/requests/{request_id}` | `get_current_user`; floor: any role | The same view as GET /prime/requests/{id} (request_hash, state, execution, decided_by), |

### `gateway/routers/questionnaire_router.py`

Tags: questionnaire. Routes: 7.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/questionnaire-stages` | `get_current_user`; floor: any role; handler calls `enforce` | The stages and their questions, so a client can build the fill-on-behalf form. |
| GET | `/questionnaire/{token}` | no auth dependency | Render questionnaire page (HTML) or return JSON for API consumers. |
| GET | `/questionnaire/{token}/status` | no auth dependency | Return completion status for polling. |
| POST | `/questionnaire/{token}/submit` | no auth dependency | Accept answers, validate, save, and signal pipeline to resume. |
| POST | `/runs/{run_id}/questionnaire/fill` | `get_current_user`; floor: member+ (viewer denied); handler calls `enforce` | Agency fills questionnaire on behalf of the client (no email link needed). |
| POST | `/runs/{run_id}/questionnaire/send` | `get_current_user`; floor: member+ (viewer denied); handler calls `enforce` | Create a QuestionnaireSession and send email link to the respondent. |
| GET | `/runs/{run_id}/questionnaires` | `get_current_user`; floor: any role; handler calls `enforce` | List all questionnaire sessions for a run, newest first. |

### `gateway/routers/run_app_router.py`

Tags: runs. Routes: 5.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/factory/runs/{run_id}/preview` | `require_run_user`, `get_current_user`; floor: any role | Serve the generated index.html for a run. |
| GET | `/factory/runs/{run_id}/preview-credentials` | `require_run_user`, `get_current_user`; floor: any role | Return demo login credentials for the generated app preview. |
| DELETE | `/factory/runs/{run_id}/run-app` | `require_run_user`, `get_current_user`; floor: member+ (viewer denied) | Kill the background app process for a run. |
| POST | `/factory/runs/{run_id}/run-app` | `require_run_user`, `get_current_user`; floor: member+ (viewer denied) | Start the generated app with uvicorn. Installs deps and builds frontend. |
| GET | `/factory/runs/{run_id}/run-app/status` | `require_run_user`, `get_current_user`; floor: any role | Return whether the generated app is currently running. |

### `gateway/routers/run_decisions_router.py`

Tags: runs. Routes: 5.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/factory/runs/{run_id}/cancel` | `get_current_user`; floor: member+ (viewer denied) | Cancel a running or paused pipeline run. |
| POST | `/factory/runs/{run_id}/kill` | `require_run_user`, `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Force-cancel a run (owner/admin only). The dashboard uses /cancel; this is the API-only hard stop. |
| POST | `/factory/runs/{run_id}/pause` | `get_current_user`; floor: member+ (viewer denied) | Signal the pipeline to pause. |
| POST | `/factory/runs/{run_id}/restart` | `get_current_user`; floor: policy engine decides; handler calls `enforce` | Restart a crashed/failed run from its last saved checkpoint. |
| POST | `/factory/runs/{run_id}/resume` | `get_current_user`; floor: member+ (viewer denied) | Resume a paused pipeline run. |

### `gateway/routers/run_deploy_router.py`

Tags: runs. Routes: 4.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/factory/runs/{run_id}/artifacts` | `get_current_user`; floor: any role; handler checks role inline | List artifacts for a run. |
| DELETE | `/factory/runs/{run_id}/deploy` | `get_current_user`; floor: member+ (viewer denied) | Stop the running Docker container (non-blocking). |
| POST | `/factory/runs/{run_id}/deploy` | `get_current_user`; floor: member+ (viewer denied) | Manually trigger Docker deployment (non-blocking). |
| GET | `/factory/runs/{run_id}/download` | `get_current_user`; floor: any role | Download all run artifacts as a ZIP. |

### `gateway/routers/run_fork_router.py`

Tags: runs. Routes: 2.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/factory/runs/{run_id}/branch` | `get_current_user`; floor: policy engine decides; handler calls `admit_run_start` | Fork a run at a given stage: a new run with the same request (plus extra_input), on a copy of its files. |
| POST | `/factory/runs/{run_id}/rerun` | `get_current_user`; floor: policy engine decides; handler calls `admit_run_start` | Create a new run of the same request, starting at `from_phase`, on a copy of the parent's files. |

### `gateway/routers/run_preview_router.py`

Tags: runs. Routes: 8.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/factory/runs/{run_id}/backend-spec` | `get_current_user`; floor: any role | Retrieve the backend spec attached to a run. |
| POST | `/factory/runs/{run_id}/backend-spec` | `get_current_user`; floor: member+ (viewer denied) | Save / overwrite the backend spec for a run. |
| POST | `/factory/runs/{run_id}/chat` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Project-scoped conversational AI endpoint. |
| GET | `/factory/runs/{run_id}/frontend-spec` | `get_current_user`; floor: any role | Retrieve the frontend spec attached to a run. |
| POST | `/factory/runs/{run_id}/frontend-spec` | `get_current_user`; floor: member+ (viewer denied) | Save / overwrite the frontend spec for a run. |
| POST | `/factory/runs/{run_id}/push-github` | `get_current_user`; floor: member+ (viewer denied) | Push the generated project to a new GitHub repository. |
| GET | `/factory/runs/{run_id}/traces` | `require_run_user`, `get_current_user`; floor: any role | Return LLM call traces for a pipeline run. |
| GET | `/factory/runs/{run_id}/traces/{trace_id}` | `require_run_user`, `get_current_user`; floor: any role | Return full prompt and response for a single trace. |

### `gateway/routers/run_spec_router.py`

Tags: runs. Routes: 8.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/admin/runs/cleanup-council-review` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Promote runs stuck in 'council_review' for > 10 minutes to 'completed'. |
| POST | `/factory/runs/{run_id}/approve-spec` | `require_run_user`, `get_current_user`; floor: member+ (viewer denied) | Approve (or cancel) the parsed spec so the pipeline continues past the review gate. |
| GET | `/factory/runs/{run_id}/council-review` | `require_run_user`, `get_current_user`; floor: any role | Get the previously generated council review for a run. |
| POST | `/factory/runs/{run_id}/council-review` | `require_run_user`, `get_current_user`; floor: member+ (viewer denied) | Run the generated src/main.py through the LLM Council for multi-model review. |
| POST | `/factory/runs/{run_id}/decisions/{decision_id}/approve` | `require_run_user`, `get_current_user`; floor: member+ (viewer denied); handler calls `enforce` | Approve a pending decision gate (member or above; a viewer reads, never decides). |
| POST | `/factory/runs/{run_id}/decisions/{decision_id}/decide` | `require_run_user`, `get_current_user`; floor: member+ (viewer denied); handler calls `enforce` | Resolve a decision gate with approve/reject (member or above). |
| GET | `/factory/runs/{run_id}/spec` | `require_run_user`, `get_current_user`; floor: any role | Return the parsed requirements spec produced by p01_intake_requirements. |
| POST | `/factory/runs/{run_id}/validate-spec` | `require_run_user`, `get_current_user`; floor: member+ (viewer denied) | Basic validation of a backend spec before pipeline starts. |

### `gateway/routers/scim_groups_router.py`

Tags: scim. Routes: 9.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/scim/v2/Groups` | `_verify_scim_auth`; handler calls `_require_admin` | List groups. |
| POST | `/scim/v2/Groups` | `_verify_scim_auth`; handler calls `_require_admin` | Create group. |
| DELETE | `/scim/v2/Groups/{group_id}` | `_verify_scim_auth`; handler calls `_require_admin` | Delete group. |
| GET | `/scim/v2/Groups/{group_id}` | `_verify_scim_auth`; handler calls `_require_admin` | Get group. |
| PATCH | `/scim/v2/Groups/{group_id}` | `_verify_scim_auth`; handler calls `_require_admin` | Patch group. |
| PUT | `/scim/v2/Groups/{group_id}` | `_verify_scim_auth`; handler calls `_require_admin` | Replace group. |
| GET | `/scim/v2/ResourceTypes` | `_verify_scim_auth` | Resource types. |
| GET | `/scim/v2/Schemas` | `_verify_scim_auth` | Schemas for `/scim/v2/Schemas`. |
| GET | `/scim/v2/ServiceProviderConfig` | `_verify_scim_auth` | Service provider config. |

### `gateway/routers/scim_router.py`

Tags: scim. Routes: 6.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/scim/v2/Users` | `_verify_scim_auth`; handler checks role inline | Scim list users. |
| POST | `/scim/v2/Users` | `_verify_scim_auth`; handler calls `enforce_seat`; handler checks role inline | SCIM provision a new user into the org. |
| DELETE | `/scim/v2/Users/{user_id}` | `_verify_scim_auth`; handler checks role inline | Scim delete user. |
| GET | `/scim/v2/Users/{user_id}` | `_verify_scim_auth`; handler checks role inline | Scim get user. |
| PATCH | `/scim/v2/Users/{user_id}` | `_verify_scim_auth` | RFC 7644 3.5.2. Supports active and userName; other attributes are accepted and ignored |
| PUT | `/scim/v2/Users/{user_id}` | `_verify_scim_auth`; handler checks role inline | Scim update user. |

### `gateway/routers/settings_advanced_router.py`

Tags: settings. Routes: 13.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/settings/council-config` | `get_current_user`; floor: any role | Get council config. |
| PUT | `/settings/council-config` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Update council config. |
| GET | `/settings/llm-config` | `get_current_user`; floor: any role | Return LLM config for the current organisation. |
| PUT | `/settings/llm-config` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Update LLM config for the current organisation. |
| GET | `/settings/phases/config` | `get_current_user`; floor: any role | Get all phase configs. |
| POST | `/settings/phases/{phase_name}/config` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Update phase config. |
| GET | `/settings/preferences` | `get_current_user`; floor: any role | Get preferences. |
| PUT | `/settings/preferences` | `get_current_user`; floor: any role | Update preferences. |
| GET | `/settings/scim` | `get_current_user`; floor: any role | Get scim config. |
| POST | `/settings/scim/rotate` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Generate a new SCIM token. DB-H1: stores only the bcrypt hash; plaintext is |
| DELETE | `/settings/sso` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Delete sso config. |
| GET | `/settings/sso` | `get_current_user`; floor: any role | Get sso config. |
| PUT | `/settings/sso` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Upsert sso config. |

### `gateway/routers/settings_router.py`

Tags: settings. Routes: 8.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/settings/active-provider` | `get_current_user`; floor: any role | Return the currently active LLM provider - called by the New Project page. |
| GET | `/settings/api-keys` | `get_current_user`; floor: any role | Return masked API key status for the current organisation. |
| POST | `/settings/api-keys` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Persist per-org API key to DB. |
| GET | `/settings/langsmith` | `get_current_user`; floor: any role | Return LangSmith configuration for this organisation. |
| POST | `/settings/langsmith` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Update LangSmith settings for the current organisation. |
| GET | `/settings/models` | `get_current_user`; floor: any role | List available LLM models with plan-based filtering. |
| POST | `/settings/models/test` | `get_current_user`; floor: member+ (viewer denied) | Test a specific model, enforcing plan-based access. |
| POST | `/settings/test-provider` | `get_current_user`; floor: policy engine decides; handler calls `enforce`; handler checks role inline | Test LLM provider connectivity. |

### `gateway/routers/spa_router.py`

Tags: spa. Routes: 2.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/dashboard` | no auth dependency | Dashboard spa missing. (hidden from OpenAPI) |
| GET | `/dashboard/{path:path}` | no auth dependency | Dashboard spa missing. (hidden from OpenAPI) |

### `gateway/routers/system_info_router.py`

Tags: system. Routes: 6.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/health/observability` | no auth dependency | Observability health - LangSmith status and today's trace count. |
| GET | `/health/sla` | `get_current_user`; floor: any role | T4-10: SLA metrics - uptime window, run completion rate, p50/p95 duration. |
| GET | `/pricing` | no auth dependency | Return pricing information. |
| GET | `/system/costs` | `get_current_user`; floor: any role | Aggregate cost summary for the current org. |
| GET | `/system/feature-flags` | `get_current_user`; floor: any role; handler checks role inline | Return current platform feature flag states (platform operator only: they are global). |
| POST | `/system/feature-flags/{flag}` | `get_current_user`; floor: member+ (viewer denied); handler checks role inline | Override a platform feature flag at runtime via env var (platform operator only). |

### `gateway/routers/system_router.py`

Tags: system. Routes: 4.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/system/health` | `get_current_user`; floor: any role | System health check with LLM provider status. |
| GET | `/system/metrics` | no auth dependency | System resource metrics - CPU, memory, disk, Redis, DB, pipeline. |
| GET | `/system/status` | no auth dependency | Minimal liveness probe - called by the frontend on every page load. |
| GET | `/system/workloop` | `get_current_user`; floor: any role; handler checks role inline | Detailed workloop monitor status: failure patterns, findings, auto-fixes (platform-wide, operator only). |

### `gateway/routers/velaris_hr_router.py`

Tags: velaris-hr. Routes: 3.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/hr/allowlist` | `get_current_user`; floor: any role | The pairs this proxy will forward (lets the UI say 'not available' instead of guessing). `admin` lists the |
| GET | `/hr/links` | `get_current_user` | Links for `/hr/links`. |
| PUT | `/hr/links/{user_id}` | `get_current_user` | Set link. |

### `gateway/routers/velaris_router.py`

Tags: velaris. Routes: 9.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/velaris/agents` | `get_current_user`; floor: any role | Velaris's agent catalogue: department, status, summary, methods (with read/act kind). |
| POST | `/velaris/agents/{agent}/{method}` | `get_current_user`; floor: any role | Run an agent method. Read methods: 200 {result}. Act methods: 202 {run} waiting for approval |
| POST | `/velaris/flows` | `get_current_user`; floor: any role | Start a model-driven run: {"task": str, "tools": ["AGENT.method", ...]}. |
| GET | `/velaris/flows/pending` | `get_current_user`; floor: any role | The caller's flow runs that wait for a decision (moves them on when Prime has decided). |
| GET | `/velaris/flows/{run_id}` | `get_current_user`; floor: any role | One of the caller's runs; Velaris moves it on if it is free to move. |
| POST | `/velaris/flows/{run_id}/decide` | `get_current_user`; floor: any role | Decide a waiting run in LOCAL mode (no Prime gate); with Prime Velaris answers 409 decided_in_prime and that |
| GET | `/velaris/flows/{run_id}/verify` | `get_current_user`; floor: any role | Check the hash chain of one of the caller's runs: {ok} or the first broken index (KAN-134). |
| GET | `/velaris/inventory` | `get_current_user`; floor: any role | Agents per department with an honest status (derived from GET /agents). |
| GET | `/velaris/trace/verify` | `get_current_user`; floor: any role | The global trace chain (counts only). Owner/admin: it spans the organisation, not one person's runs. |

### `gateway/routers/webhooks_router.py`

Tags: webhooks. Routes: 5.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/webhooks` | `get_current_user`; floor: any role | List webhooks. |
| POST | `/webhooks` | `get_current_user`; floor: admin+ | Create webhook. |
| DELETE | `/webhooks/{webhook_id}` | `get_current_user`; floor: admin+ | Delete webhook. |
| PUT | `/webhooks/{webhook_id}` | `get_current_user`; floor: admin+ | Update webhook. |
| POST | `/webhooks/{webhook_id}/test` | `get_current_user`; floor: admin+ | Test webhook. |

### `gateway/routers/workspaces_router.py`

Tags: workspaces. Routes: 5.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/workspaces` | `get_current_user`; floor: any role | List workspaces. |
| POST | `/workspaces` | `get_current_user`; floor: member+ (viewer denied) | Create workspace. |
| DELETE | `/workspaces/{workspace_id}` | `get_current_user`; floor: member+ (viewer denied) | Delete workspace. |
| GET | `/workspaces/{workspace_id}` | `get_current_user`; floor: any role | Get workspace. |
| PUT | `/workspaces/{workspace_id}` | `get_current_user`; floor: member+ (viewer denied) | Update workspace. |

### `gateway/velaris_proxy.py`

Tags: velaris-chat, velaris-control, velaris-hr, velaris-mail, velaris-providers. Routes: 300.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/chat/admin/channels/{channel_id}/export` | `get_current_user`; floor: any role | Velaris chat admin export get. |
| PUT | `/chat/admin/channels/{channel_id}/hold` | `get_current_user`; floor: any role | Velaris chat admin hold put. |
| POST | `/chat/admin/messages/{message_id}/erase` | `get_current_user`; floor: any role | Velaris chat admin erase post. |
| GET | `/chat/admin/settings` | `get_current_user`; floor: any role | Velaris chat admin settings get. |
| PUT | `/chat/admin/settings` | `get_current_user`; floor: any role | Velaris chat admin settings set put. |
| POST | `/chat/admin/sweep` | `get_current_user`; floor: any role | Velaris chat admin sweep post. |
| POST | `/chat/admin/users/{user_id}/erase` | `get_current_user`; floor: any role | Velaris chat admin user erase post. |
| GET | `/chat/admin/users/{user_id}/export` | `get_current_user`; floor: any role | Velaris chat admin user export get. |
| GET | `/chat/assistant/drafts` | `get_current_user`; floor: any role | Velaris chat assistant drafts get. |
| POST | `/chat/assistant/drafts/{draft_id}/confirm` | `get_current_user`; floor: any role | Velaris chat assistant draft confirm post. |
| POST | `/chat/assistant/drafts/{draft_id}/discard` | `get_current_user`; floor: any role | Velaris chat assistant draft discard post. |
| GET | `/chat/assistant/proposals` | `get_current_user`; floor: any role | Velaris chat assistant proposals get. |
| POST | `/chat/assistant/proposals/{run_id}/confirm` | `get_current_user`; floor: any role | Velaris chat assistant proposal confirm post. |
| POST | `/chat/assistant/proposals/{run_id}/decide` | `get_current_user`; floor: any role | Velaris chat assistant proposal decide post. |
| GET | `/chat/channels` | `get_current_user`; floor: any role | Velaris chat channels get. |
| POST | `/chat/channels` | `get_current_user`; floor: any role | Velaris chat channel create post. |
| GET | `/chat/channels/public` | `get_current_user`; floor: any role | Velaris chat channels public get. |
| GET | `/chat/channels/{channel_id}` | `get_current_user`; floor: any role | Velaris chat channel get get. |
| PATCH | `/chat/channels/{channel_id}` | `get_current_user`; floor: any role | Velaris chat channel update patch. |
| PUT | `/chat/channels/{channel_id}/draft` | `get_current_user`; floor: any role | Velaris chat draft set put. |
| POST | `/chat/channels/{channel_id}/join` | `get_current_user`; floor: any role | Velaris chat channel join post. |
| POST | `/chat/channels/{channel_id}/leave` | `get_current_user`; floor: any role | Velaris chat channel leave post. |
| POST | `/chat/channels/{channel_id}/members` | `get_current_user`; floor: any role | Velaris chat member add post. |
| DELETE | `/chat/channels/{channel_id}/members/{user_id}` | `get_current_user`; floor: any role | Velaris chat member remove delete. |
| PUT | `/chat/channels/{channel_id}/members/{user_id}/role` | `get_current_user`; floor: any role | Velaris chat member role put. |
| GET | `/chat/channels/{channel_id}/messages` | `get_current_user`; floor: any role | Velaris chat messages get. |
| POST | `/chat/channels/{channel_id}/messages` | `get_current_user`; floor: any role | Velaris chat message post post. |
| GET | `/chat/channels/{channel_id}/pins` | `get_current_user`; floor: any role | Velaris chat pins get. |
| POST | `/chat/channels/{channel_id}/read` | `get_current_user`; floor: any role | Velaris chat read post. |
| GET | `/chat/channels/{channel_id}/topics` | `get_current_user`; floor: any role | Velaris chat topics get. |
| GET | `/chat/drafts` | `get_current_user`; floor: any role | Velaris chat drafts get. |
| GET | `/chat/events` | `get_current_user`; floor: any role | Velaris chat events get. |
| GET | `/chat/events/stream` | `get_current_user`; floor: any role | Velaris chat events stream get. |
| POST | `/chat/files` | `get_current_user`; floor: any role | Velaris chat file upload post. |
| GET | `/chat/files/{digest}` | `get_current_user`; floor: any role | Velaris chat file download get. |
| GET | `/chat/me/export` | `get_current_user`; floor: any role | Velaris chat me export get. |
| DELETE | `/chat/messages/{message_id}` | `get_current_user`; floor: any role | Velaris chat message delete delete. |
| PATCH | `/chat/messages/{message_id}` | `get_current_user`; floor: any role | Velaris chat message edit patch. |
| GET | `/chat/messages/{message_id}/history` | `get_current_user`; floor: any role | Velaris chat message history get. |
| DELETE | `/chat/messages/{message_id}/pin` | `get_current_user`; floor: any role | Velaris chat unpin delete. |
| PUT | `/chat/messages/{message_id}/pin` | `get_current_user`; floor: any role | Velaris chat pin put. |
| DELETE | `/chat/messages/{message_id}/reactions/{emoji}` | `get_current_user`; floor: any role | Velaris chat unreact delete. |
| PUT | `/chat/messages/{message_id}/reactions/{emoji}` | `get_current_user`; floor: any role | Velaris chat react put. |
| GET | `/chat/messages/{message_id}/unfurl` | `get_current_user`; floor: any role | Velaris chat message unfurl get. |
| DELETE | `/chat/queues/{queue_id}` | `get_current_user`; floor: any role | Velaris chat queue drop delete. |
| POST | `/chat/register` | `get_current_user`; floor: any role | Velaris chat register post. |
| GET | `/chat/search` | `get_current_user`; floor: any role | Velaris chat search get. |
| GET | `/control/pending` | `get_current_user`; floor: any role | Velaris control pending get. |
| POST | `/control/runs` | `get_current_user`; floor: any role | Velaris control start post. |
| GET | `/control/runs/{run_id}` | `get_current_user`; floor: any role | Velaris control state get. |
| POST | `/control/runs/{run_id}/decide` | `get_current_user`; floor: any role | Velaris control decide post. |
| POST | `/control/runs/{run_id}/kill` | `get_current_user`; floor: any role | Velaris control kill post. |
| GET | `/control/runs/{run_id}/report` | `get_current_user`; floor: any role | Velaris control report get. |
| POST | `/control/runs/{run_id}/undo` | `get_current_user`; floor: any role | Velaris control undo post. |
| GET | `/control/tasks` | `get_current_user`; floor: any role | Velaris control tasks get. |
| POST | `/hr/ATS_CORE/add_application` | `get_current_user`; floor: any role | Velaris HR ats core: add application. |
| POST | `/hr/ATS_CORE/add_candidate` | `get_current_user`; floor: any role | Velaris HR ats core: add candidate. |
| POST | `/hr/ATS_CORE/aggregate_counts` | `get_current_user`; floor: any role | Velaris HR ats core: aggregate counts. |
| POST | `/hr/ATS_CORE/approve_requisition` | `get_current_user`; floor: any role | Velaris HR ats core: approve requisition. |
| POST | `/hr/ATS_CORE/candidate_contact` | `get_current_user`; floor: any role | Velaris HR ats core: candidate contact. |
| POST | `/hr/ATS_CORE/candidate_summary` | `get_current_user`; floor: any role | Velaris HR ats core: candidate summary. |
| POST | `/hr/ATS_CORE/close_requisition` | `get_current_user`; floor: any role | Velaris HR ats core: close requisition. |
| POST | `/hr/ATS_CORE/create_requisition` | `get_current_user`; floor: any role | Velaris HR ats core: create requisition. |
| POST | `/hr/ATS_CORE/decision_log` | `get_current_user`; floor: any role | Velaris HR ats core: decision log. |
| POST | `/hr/ATS_CORE/duplicate_review` | `get_current_user`; floor: any role | Velaris HR ats core: duplicate review. |
| POST | `/hr/ATS_CORE/erase_candidates` | `get_current_user`; floor: any role | Velaris HR ats core: erase candidates. |
| POST | `/hr/ATS_CORE/export_candidate` | `get_current_user`; floor: any role | Velaris HR ats core: export candidate. |
| POST | `/hr/ATS_CORE/get_application` | `get_current_user`; floor: any role | Velaris HR ats core: get application. |
| POST | `/hr/ATS_CORE/get_requisition` | `get_current_user`; floor: any role | Velaris HR ats core: get requisition. |
| POST | `/hr/ATS_CORE/list_requisitions` | `get_current_user`; floor: any role | Velaris HR ats core: list requisitions. |
| POST | `/hr/ATS_CORE/move_stage` | `get_current_user`; floor: any role | Velaris HR ats core: move stage. |
| POST | `/hr/ATS_CORE/open_requisition` | `get_current_user`; floor: any role | Velaris HR ats core: open requisition. |
| POST | `/hr/ATS_CORE/pipeline` | `get_current_user`; floor: any role | Velaris HR ats core: pipeline. |
| POST | `/hr/ATS_CORE/record_offer_outcome` | `get_current_user`; floor: any role | Velaris HR ats core: record offer outcome. |
| POST | `/hr/ATS_CORE/resolve_duplicate` | `get_current_user`; floor: any role | Velaris HR ats core: resolve duplicate. |
| POST | `/hr/ATS_CORE/retention_due` | `get_current_user`; floor: any role | Velaris HR ats core: retention due. |
| POST | `/hr/ATS_CORE/withdraw_consent` | `get_current_user`; floor: any role | Velaris HR ats core: withdraw consent. |
| POST | `/hr/EMPLOYEE_RECORDS/approve_conversion` | `get_current_user`; floor: any role | Velaris HR employee records: approve conversion. |
| POST | `/hr/EMPLOYEE_RECORDS/change_record` | `get_current_user`; floor: any role | Velaris HR employee records: change record. |
| POST | `/hr/EMPLOYEE_RECORDS/complete_exit_task` | `get_current_user`; floor: any role | Velaris HR employee records: complete exit task. |
| POST | `/hr/EMPLOYEE_RECORDS/employee_history` | `get_current_user`; floor: any role | Velaris HR employee records: employee history. |
| POST | `/hr/EMPLOYEE_RECORDS/erase_subject` | `get_current_user`; floor: any role | Velaris HR employee records: erase subject. |
| POST | `/hr/EMPLOYEE_RECORDS/exit_status` | `get_current_user`; floor: any role | Velaris HR employee records: exit status. |
| POST | `/hr/EMPLOYEE_RECORDS/export_subject` | `get_current_user`; floor: any role | Velaris HR employee records: export subject. |
| POST | `/hr/EMPLOYEE_RECORDS/finalise_exit` | `get_current_user`; floor: any role | Velaris HR employee records: finalise exit. |
| POST | `/hr/EMPLOYEE_RECORDS/get_employee` | `get_current_user`; floor: any role | Velaris HR employee records: get employee. |
| POST | `/hr/EMPLOYEE_RECORDS/list_employees` | `get_current_user`; floor: any role | Velaris HR employee records: list employees. |
| POST | `/hr/EMPLOYEE_RECORDS/propose_conversion` | `get_current_user`; floor: any role | Velaris HR employee records: propose conversion. |
| POST | `/hr/EMPLOYEE_RECORDS/reject_conversion` | `get_current_user`; floor: any role | Velaris HR employee records: reject conversion. |
| POST | `/hr/EMPLOYEE_RECORDS/retention_status` | `get_current_user`; floor: any role | Velaris HR employee records: retention status. |
| POST | `/hr/EMPLOYEE_RECORDS/retention_table` | `get_current_user`; floor: any role | Velaris HR employee records: retention table. |
| POST | `/hr/EMPLOYEE_RECORDS/start_exit` | `get_current_user`; floor: any role | Velaris HR employee records: start exit. |
| POST | `/hr/EMPLOYEE_RECORDS/workforce_aggregate` | `get_current_user`; floor: any role | Velaris HR employee records: workforce aggregate. |
| POST | `/hr/ESIGN/create_request` | `get_current_user`; floor: any role | Velaris HR esign: create request. |
| POST | `/hr/ESIGN/get_request` | `get_current_user`; floor: any role | Velaris HR esign: get request. |
| POST | `/hr/ESIGN/get_sealed_document` | `get_current_user`; floor: any role | Velaris HR esign: get sealed document. |
| POST | `/hr/ESIGN/list_requests` | `get_current_user`; floor: any role | Velaris HR esign: list requests. |
| POST | `/hr/ESIGN/process_due` | `get_current_user`; floor: any role | Velaris HR esign: process due. |
| POST | `/hr/ESIGN/seal_request` | `get_current_user`; floor: any role | Velaris HR esign: seal request. |
| POST | `/hr/ESIGN/send_reminders` | `get_current_user`; floor: any role | Velaris HR esign: send reminders. |
| POST | `/hr/ESIGN/send_request` | `get_current_user`; floor: any role | Velaris HR esign: send request. |
| POST | `/hr/ESIGN/verify` | `get_current_user`; floor: any role | Velaris HR esign: verify. |
| POST | `/hr/ESIGN/void_request` | `get_current_user`; floor: any role | Velaris HR esign: void request. |
| POST | `/hr/INTERVIEW_KIT/add_question` | `get_current_user`; floor: any role | Velaris HR interview kit: add question. |
| POST | `/hr/INTERVIEW_KIT/agreement_report` | `get_current_user`; floor: any role | Velaris HR interview kit: agreement report. |
| POST | `/hr/INTERVIEW_KIT/assign_panel` | `get_current_user`; floor: any role | Velaris HR interview kit: assign panel. |
| POST | `/hr/INTERVIEW_KIT/calibration_report` | `get_current_user`; floor: any role | Velaris HR interview kit: calibration report. |
| POST | `/hr/INTERVIEW_KIT/create_kit` | `get_current_user`; floor: any role | Velaris HR interview kit: create kit. |
| POST | `/hr/INTERVIEW_KIT/create_work_sample` | `get_current_user`; floor: any role | Velaris HR interview kit: create work sample. |
| POST | `/hr/INTERVIEW_KIT/define_rubric` | `get_current_user`; floor: any role | Velaris HR interview kit: define rubric. |
| POST | `/hr/INTERVIEW_KIT/get_kit` | `get_current_user`; floor: any role | Velaris HR interview kit: get kit. |
| POST | `/hr/INTERVIEW_KIT/list_questions` | `get_current_user`; floor: any role | Velaris HR interview kit: list questions. |
| POST | `/hr/INTERVIEW_KIT/list_work_samples` | `get_current_user`; floor: any role | Velaris HR interview kit: list work samples. |
| POST | `/hr/INTERVIEW_KIT/review_work_sample` | `get_current_user`; floor: any role | Velaris HR interview kit: review work sample. |
| POST | `/hr/INTERVIEW_KIT/scorecards` | `get_current_user`; floor: any role | Velaris HR interview kit: scorecards. |
| POST | `/hr/INTERVIEW_KIT/submit_scorecard` | `get_current_user`; floor: any role | Velaris HR interview kit: submit scorecard. |
| POST | `/hr/INTERVIEW_KIT/work_sample_reviews` | `get_current_user`; floor: any role | Velaris HR interview kit: work sample reviews. |
| POST | `/hr/INTERVIEW_RECORD/close_session` | `get_current_user`; floor: any role | Velaris HR interview record: close session. |
| POST | `/hr/INTERVIEW_RECORD/create_session` | `get_current_user`; floor: any role | Velaris HR interview record: create session. |
| POST | `/hr/INTERVIEW_RECORD/evidence_view` | `get_current_user`; floor: any role | Velaris HR interview record: evidence view. |
| POST | `/hr/INTERVIEW_RECORD/issue_participant_token` | `get_current_user`; floor: any role | Velaris HR interview record: issue participant token. |
| POST | `/hr/INTERVIEW_RECORD/list_sessions` | `get_current_user`; floor: any role | Velaris HR interview record: list sessions. |
| POST | `/hr/INTERVIEW_RECORD/mark_event` | `get_current_user`; floor: any role | Velaris HR interview record: mark event. |
| POST | `/hr/INTERVIEW_RECORD/replay_pad` | `get_current_user`; floor: any role | Velaris HR interview record: replay pad. |
| POST | `/hr/INTERVIEW_SCHEDULER/approve_draft` | `get_current_user`; floor: any role | Velaris HR interview scheduler: approve draft. |
| POST | `/hr/INTERVIEW_SCHEDULER/book_interview` | `get_current_user`; floor: any role | Velaris HR interview scheduler: book interview. |
| POST | `/hr/INTERVIEW_SCHEDULER/cancel_interview` | `get_current_user`; floor: any role | Velaris HR interview scheduler: cancel interview. |
| POST | `/hr/INTERVIEW_SCHEDULER/complete_interview` | `get_current_user`; floor: any role | Velaris HR interview scheduler: complete interview. |
| POST | `/hr/INTERVIEW_SCHEDULER/issue_schedule_token` | `get_current_user`; floor: any role | Velaris HR interview scheduler: issue schedule token. |
| POST | `/hr/INTERVIEW_SCHEDULER/list_bookings` | `get_current_user`; floor: any role | Velaris HR interview scheduler: list bookings. |
| POST | `/hr/INTERVIEW_SCHEDULER/list_drafts` | `get_current_user`; floor: any role | Velaris HR interview scheduler: list drafts. |
| POST | `/hr/INTERVIEW_SCHEDULER/list_interviewers` | `get_current_user`; floor: any role | Velaris HR interview scheduler: list interviewers. |
| POST | `/hr/INTERVIEW_SCHEDULER/mark_no_show` | `get_current_user`; floor: any role | Velaris HR interview scheduler: mark no show. |
| POST | `/hr/INTERVIEW_SCHEDULER/mark_reminder_sent` | `get_current_user`; floor: any role | Velaris HR interview scheduler: mark reminder sent. |
| POST | `/hr/INTERVIEW_SCHEDULER/propose_slots` | `get_current_user`; floor: any role | Velaris HR interview scheduler: propose slots. |
| POST | `/hr/INTERVIEW_SCHEDULER/reminders` | `get_current_user`; floor: any role | Velaris HR interview scheduler: reminders. |
| POST | `/hr/INTERVIEW_SCHEDULER/render_invitation` | `get_current_user`; floor: any role | Velaris HR interview scheduler: render invitation. |
| POST | `/hr/INTERVIEW_SCHEDULER/reschedule_interview` | `get_current_user`; floor: any role | Velaris HR interview scheduler: reschedule interview. |
| POST | `/hr/INTERVIEW_SCHEDULER/set_availability` | `get_current_user`; floor: any role | Velaris HR interview scheduler: set availability. |
| POST | `/hr/JOB_POSTINGS/approve_pack` | `get_current_user`; floor: any role | Velaris HR job postings: approve pack. |
| POST | `/hr/JOB_POSTINGS/approve_posting` | `get_current_user`; floor: any role | Velaris HR job postings: approve posting. |
| POST | `/hr/JOB_POSTINGS/get_company_profile` | `get_current_user`; floor: any role | Velaris HR job postings: get company profile. |
| POST | `/hr/JOB_POSTINGS/get_posting` | `get_current_user`; floor: any role | Velaris HR job postings: get posting. |
| POST | `/hr/JOB_POSTINGS/list_packs` | `get_current_user`; floor: any role | Velaris HR job postings: list packs. |
| POST | `/hr/JOB_POSTINGS/mark_pack_posted` | `get_current_user`; floor: any role | Velaris HR job postings: mark pack posted. |
| POST | `/hr/JOB_POSTINGS/mark_pack_taken_down` | `get_current_user`; floor: any role | Velaris HR job postings: mark pack taken down. |
| POST | `/hr/JOB_POSTINGS/mark_posting_live` | `get_current_user`; floor: any role | Velaris HR job postings: mark posting live. |
| POST | `/hr/JOB_POSTINGS/prepare_careers_posting` | `get_current_user`; floor: any role | Velaris HR job postings: prepare careers posting. |
| POST | `/hr/JOB_POSTINGS/prepare_pack` | `get_current_user`; floor: any role | Velaris HR job postings: prepare pack. |
| POST | `/hr/JOB_POSTINGS/resolve_tracking` | `get_current_user`; floor: any role | Velaris HR job postings: resolve tracking. |
| POST | `/hr/JOB_POSTINGS/send_indexing_notification` | `get_current_user`; floor: any role | Velaris HR job postings: send indexing notification. |
| POST | `/hr/JOB_POSTINGS/set_company_profile` | `get_current_user`; floor: any role | Velaris HR job postings: set company profile. |
| POST | `/hr/JOB_POSTINGS/take_down_posting` | `get_current_user`; floor: any role | Velaris HR job postings: take down posting. |
| POST | `/hr/JOB_POSTINGS/takedown_due` | `get_current_user`; floor: any role | Velaris HR job postings: takedown due. |
| POST | `/hr/LEAVE_MANAGEMENT/apply` | `get_current_user`; floor: any role | Velaris HR leave management: apply. |
| POST | `/hr/LEAVE_MANAGEMENT/approve` | `get_current_user`; floor: any role | Velaris HR leave management: approve. |
| POST | `/hr/LEAVE_MANAGEMENT/employee_history` | `get_current_user`; floor: any role | Velaris HR leave management: employee history. |
| POST | `/hr/LEAVE_MANAGEMENT/get_balance` | `get_current_user`; floor: any role | Velaris HR leave management: get balance. |
| POST | `/hr/LEAVE_MANAGEMENT/pending_approvals` | `get_current_user`; floor: any role | Velaris HR leave management: pending approvals. |
| POST | `/hr/LEAVE_MANAGEMENT/reject` | `get_current_user`; floor: any role | Velaris HR leave management: reject. |
| POST | `/hr/OFFER_LETTERS/add_template` | `get_current_user`; floor: any role | Velaris HR offer letters: add template. |
| POST | `/hr/OFFER_LETTERS/approve` | `get_current_user`; floor: any role | Velaris HR offer letters: approve. |
| POST | `/hr/OFFER_LETTERS/compensation_preview` | `get_current_user`; floor: any role | Velaris HR offer letters: compensation preview. |
| POST | `/hr/OFFER_LETTERS/create_offer` | `get_current_user`; floor: any role | Velaris HR offer letters: create offer. |
| POST | `/hr/OFFER_LETTERS/expire_due` | `get_current_user`; floor: any role | Velaris HR offer letters: expire due. |
| POST | `/hr/OFFER_LETTERS/get_offer` | `get_current_user`; floor: any role | Velaris HR offer letters: get offer. |
| POST | `/hr/OFFER_LETTERS/list_offers` | `get_current_user`; floor: any role | Velaris HR offer letters: list offers. |
| POST | `/hr/OFFER_LETTERS/list_templates` | `get_current_user`; floor: any role | Velaris HR offer letters: list templates. |
| POST | `/hr/OFFER_LETTERS/record_response` | `get_current_user`; floor: any role | Velaris HR offer letters: record response. |
| POST | `/hr/OFFER_LETTERS/reject` | `get_current_user`; floor: any role | Velaris HR offer letters: reject. |
| POST | `/hr/OFFER_LETTERS/render_offer` | `get_current_user`; floor: any role | Velaris HR offer letters: render offer. |
| POST | `/hr/OFFER_LETTERS/revise_offer` | `get_current_user`; floor: any role | Velaris HR offer letters: revise offer. |
| POST | `/hr/OFFER_LETTERS/send_offer` | `get_current_user`; floor: any role | Velaris HR offer letters: send offer. |
| POST | `/hr/OFFER_LETTERS/submit_for_approval` | `get_current_user`; floor: any role | Velaris HR offer letters: submit for approval. |
| POST | `/hr/OFFER_LETTERS/withdraw_offer` | `get_current_user`; floor: any role | Velaris HR offer letters: withdraw offer. |
| POST | `/hr/ONBOARDING_FLOW/cancel_case` | `get_current_user`; floor: any role | Velaris HR onboarding flow: cancel case. |
| POST | `/hr/ONBOARDING_FLOW/case_status` | `get_current_user`; floor: any role | Velaris HR onboarding flow: case status. |
| POST | `/hr/ONBOARDING_FLOW/check_aadhaar` | `get_current_user`; floor: any role | Velaris HR onboarding flow: check aadhaar. |
| POST | `/hr/ONBOARDING_FLOW/collect_document` | `get_current_user`; floor: any role | Velaris HR onboarding flow: collect document. |
| POST | `/hr/ONBOARDING_FLOW/complete_task` | `get_current_user`; floor: any role | Velaris HR onboarding flow: complete task. |
| POST | `/hr/ONBOARDING_FLOW/get_document` | `get_current_user`; floor: any role | Velaris HR onboarding flow: get document. |
| POST | `/hr/ONBOARDING_FLOW/get_form` | `get_current_user`; floor: any role | Velaris HR onboarding flow: get form. |
| POST | `/hr/ONBOARDING_FLOW/get_identifiers` | `get_current_user`; floor: any role | Velaris HR onboarding flow: get identifiers. |
| POST | `/hr/ONBOARDING_FLOW/list_cases` | `get_current_user`; floor: any role | Velaris HR onboarding flow: list cases. |
| POST | `/hr/ONBOARDING_FLOW/list_templates` | `get_current_user`; floor: any role | Velaris HR onboarding flow: list templates. |
| POST | `/hr/ONBOARDING_FLOW/reminders_due` | `get_current_user`; floor: any role | Velaris HR onboarding flow: reminders due. |
| POST | `/hr/ONBOARDING_FLOW/start_onboarding` | `get_current_user`; floor: any role | Velaris HR onboarding flow: start onboarding. |
| POST | `/hr/ONBOARDING_FLOW/submit_form` | `get_current_user`; floor: any role | Velaris HR onboarding flow: submit form. |
| POST | `/hr/ONBOARDING_FLOW/submit_identifier` | `get_current_user`; floor: any role | Velaris HR onboarding flow: submit identifier. |
| POST | `/hr/ONBOARDING_FLOW/waive_task` | `get_current_user`; floor: any role | Velaris HR onboarding flow: waive task. |
| POST | `/hr/PAYROLL_ENGINE/compute` | `get_current_user`; floor: any role | Velaris HR payroll engine: compute. |
| POST | `/hr/PAYROLL_ENGINE/compute_bulk` | `get_current_user`; floor: any role | Velaris HR payroll engine: compute bulk. |
| POST | `/hr/PAYROLL_ENGINE/get_payslip` | `get_current_user`; floor: any role | Velaris HR payroll engine: get payslip. |
| POST | `/hr/PAYROLL_ENGINE/get_statutory_deductions` | `get_current_user`; floor: any role | Velaris HR payroll engine: get statutory deductions. |
| POST | `/hr/PAYROLL_ENGINE/get_ytd_summary` | `get_current_user`; floor: any role | Velaris HR payroll engine: get ytd summary. |
| POST | `/hr/PAYROLL_ENGINE/org_statutory_summary` | `get_current_user`; floor: any role | Velaris HR payroll engine: org statutory summary. |
| POST | `/hr/POLICY_ACKS/acknowledge` | `get_current_user`; floor: any role | Velaris HR policy acks: acknowledge. |
| POST | `/hr/POLICY_ACKS/compliance_report` | `get_current_user`; floor: any role | Velaris HR policy acks: compliance report. |
| POST | `/hr/POLICY_ACKS/get_policy` | `get_current_user`; floor: any role | Velaris HR policy acks: get policy. |
| POST | `/hr/POLICY_ACKS/list_policies` | `get_current_user`; floor: any role | Velaris HR policy acks: list policies. |
| POST | `/hr/POLICY_ACKS/pending_for_employee` | `get_current_user`; floor: any role | Velaris HR policy acks: pending for employee. |
| POST | `/hr/POLICY_ACKS/publish_policy` | `get_current_user`; floor: any role | Velaris HR policy acks: publish policy. |
| POST | `/hr/POLICY_ACKS/reminders_due` | `get_current_user`; floor: any role | Velaris HR policy acks: reminders due. |
| POST | `/hr/POLICY_ACKS/retire_policy` | `get_current_user`; floor: any role | Velaris HR policy acks: retire policy. |
| POST | `/hr/RESUME_EVIDENCE/alias_proposals` | `get_current_user`; floor: any role | Velaris HR resume evidence: alias proposals. |
| POST | `/hr/RESUME_EVIDENCE/bias_audit` | `get_current_user`; floor: any role | Velaris HR resume evidence: bias audit. |
| POST | `/hr/RESUME_EVIDENCE/get_evidence` | `get_current_user`; floor: any role | Velaris HR resume evidence: get evidence. |
| POST | `/hr/RESUME_EVIDENCE/list_skills` | `get_current_user`; floor: any role | Velaris HR resume evidence: list skills. |
| POST | `/hr/RESUME_EVIDENCE/match_requisition` | `get_current_user`; floor: any role | Velaris HR resume evidence: match requisition. |
| POST | `/hr/RESUME_EVIDENCE/parse_resume` | `get_current_user`; floor: any role | Velaris HR resume evidence: parse resume. |
| POST | `/hr/RESUME_EVIDENCE/propose_alias` | `get_current_user`; floor: any role | Velaris HR resume evidence: propose alias. |
| POST | `/hr/RESUME_EVIDENCE/review_alias` | `get_current_user`; floor: any role | Velaris HR resume evidence: review alias. |
| POST | `/hr/RESUME_EVIDENCE/unknown_skills` | `get_current_user`; floor: any role | Velaris HR resume evidence: unknown skills. |
| POST | `/hr/SCREENING_FORMS/accept_submission` | `get_current_user`; floor: any role | Velaris HR screening forms: accept submission. |
| POST | `/hr/SCREENING_FORMS/create_form` | `get_current_user`; floor: any role | Velaris HR screening forms: create form. |
| POST | `/hr/SCREENING_FORMS/discard_submission` | `get_current_user`; floor: any role | Velaris HR screening forms: discard submission. |
| POST | `/hr/SCREENING_FORMS/get_form` | `get_current_user`; floor: any role | Velaris HR screening forms: get form. |
| POST | `/hr/SCREENING_FORMS/get_submission` | `get_current_user`; floor: any role | Velaris HR screening forms: get submission. |
| POST | `/hr/SCREENING_FORMS/issue_candidate_token` | `get_current_user`; floor: any role | Velaris HR screening forms: issue candidate token. |
| POST | `/hr/SCREENING_FORMS/list_forms` | `get_current_user`; floor: any role | Velaris HR screening forms: list forms. |
| POST | `/hr/SCREENING_FORMS/pending_submissions` | `get_current_user`; floor: any role | Velaris HR screening forms: pending submissions. |
| POST | `/hr/SCREENING_FORMS/process_withdrawal` | `get_current_user`; floor: any role | Velaris HR screening forms: process withdrawal. |
| POST | `/hr/SCREENING_FORMS/public_routes` | `get_current_user`; floor: any role | Velaris HR screening forms: public routes. |
| POST | `/hr/SCREENING_FORMS/publish_form` | `get_current_user`; floor: any role | Velaris HR screening forms: publish form. |
| POST | `/hr/SCREENING_FORMS/sweep_submissions` | `get_current_user`; floor: any role | Velaris HR screening forms: sweep submissions. |
| POST | `/hr/SCREENING_FORMS/unpublish_form` | `get_current_user`; floor: any role | Velaris HR screening forms: unpublish form. |
| POST | `/hr/SCREENING_FORMS/withdrawal_requests` | `get_current_user`; floor: any role | Velaris HR screening forms: withdrawal requests. |
| POST | `/hr/ZOHO_PAYROLL/get_cost_to_company` | `get_current_user`; floor: any role | Velaris HR zoho payroll: get cost to company. |
| POST | `/hr/ZOHO_PAYROLL/get_payslip` | `get_current_user`; floor: any role | Velaris HR zoho payroll: get payslip. |
| POST | `/hr/ZOHO_PAYROLL/get_statutory_deductions` | `get_current_user`; floor: any role | Velaris HR zoho payroll: get statutory deductions. |
| POST | `/hr/ZOHO_PAYROLL/get_ytd_summary` | `get_current_user`; floor: any role | Velaris HR zoho payroll: get ytd summary. |
| POST | `/hr/ZOHO_PEOPLE/get_attendance` | `get_current_user`; floor: any role | Velaris HR zoho people: get attendance. |
| POST | `/hr/ZOHO_PEOPLE/get_attendance_summary` | `get_current_user`; floor: any role | Velaris HR zoho people: get attendance summary. |
| POST | `/hr/ZOHO_PEOPLE/get_employees` | `get_current_user`; floor: any role | Velaris HR zoho people: get employees. |
| POST | `/hr/ZOHO_PEOPLE/get_leave_summary` | `get_current_user`; floor: any role | Velaris HR zoho people: get leave summary. |
| GET | `/mail/approvals` | `get_current_user`; floor: any role | Velaris mail approvals get. |
| GET | `/mail/domains` | `get_current_user`; floor: any role | Velaris mail domains get. |
| POST | `/mail/domains` | `get_current_user`; floor: any role | Velaris mail domain claim post. |
| POST | `/mail/domains/verify` | `get_current_user`; floor: any role | Velaris mail domain verify post. |
| GET | `/mail/mailboxes` | `get_current_user`; floor: any role | Velaris mail mailboxes get. |
| POST | `/mail/mailboxes` | `get_current_user`; floor: any role | Velaris mail mailbox create post. |
| DELETE | `/mail/mailboxes/{mb}` | `get_current_user`; floor: any role | Velaris mail mailbox erase delete. |
| GET | `/mail/mailboxes/{mb}/accounts` | `get_current_user`; floor: any role | Velaris mail accounts get. |
| POST | `/mail/mailboxes/{mb}/accounts` | `get_current_user`; floor: any role | Velaris mail account create post. |
| DELETE | `/mail/mailboxes/{mb}/accounts/{aid}` | `get_current_user`; floor: any role | Velaris mail account delete delete. |
| PUT | `/mail/mailboxes/{mb}/aliases` | `get_current_user`; floor: any role | Velaris mail mailbox aliases put. |
| POST | `/mail/mailboxes/{mb}/assistant/action-items` | `get_current_user`; floor: any role | Velaris mail assistant action items post. |
| POST | `/mail/mailboxes/{mb}/assistant/draft-reply` | `get_current_user`; floor: any role | Velaris mail assistant draft reply post. |
| POST | `/mail/mailboxes/{mb}/assistant/summarise` | `get_current_user`; floor: any role | Velaris mail assistant summarise post. |
| POST | `/mail/mailboxes/{mb}/assistant/triage` | `get_current_user`; floor: any role | Velaris mail assistant triage post. |
| DELETE | `/mail/mailboxes/{mb}/delegates` | `get_current_user`; floor: any role | Velaris mail delegate remove delete. |
| GET | `/mail/mailboxes/{mb}/delegates` | `get_current_user`; floor: any role | Velaris mail delegates get. |
| PUT | `/mail/mailboxes/{mb}/delegates` | `get_current_user`; floor: any role | Velaris mail delegate add put. |
| POST | `/mail/mailboxes/{mb}/drafts` | `get_current_user`; floor: any role | Velaris mail draft create post. |
| DELETE | `/mail/mailboxes/{mb}/drafts/{did}` | `get_current_user`; floor: any role | Velaris mail draft delete delete. |
| PUT | `/mail/mailboxes/{mb}/drafts/{did}` | `get_current_user`; floor: any role | Velaris mail draft update put. |
| POST | `/mail/mailboxes/{mb}/drafts/{did}/submit` | `get_current_user`; floor: any role | Velaris mail submit post. |
| GET | `/mail/mailboxes/{mb}/export` | `get_current_user`; floor: any role | Velaris mail export get. |
| GET | `/mail/mailboxes/{mb}/folders` | `get_current_user`; floor: any role | Velaris mail folders get. |
| POST | `/mail/mailboxes/{mb}/folders` | `get_current_user`; floor: any role | Velaris mail folder create post. |
| PUT | `/mail/mailboxes/{mb}/legal-hold` | `get_current_user`; floor: any role | Velaris mail legal hold put. |
| GET | `/mail/mailboxes/{mb}/messages` | `get_current_user`; floor: any role | Velaris mail messages get. |
| DELETE | `/mail/mailboxes/{mb}/messages/{mid}` | `get_current_user`; floor: any role | Velaris mail message delete delete. |
| GET | `/mail/mailboxes/{mb}/messages/{mid}` | `get_current_user`; floor: any role | Velaris mail message get. |
| PATCH | `/mail/mailboxes/{mb}/messages/{mid}` | `get_current_user`; floor: any role | Velaris mail message update patch. |
| GET | `/mail/mailboxes/{mb}/messages/{mid}/attachments/{sha}` | `get_current_user`; floor: any role | Velaris mail attachment get. |
| POST | `/mail/mailboxes/{mb}/messages/{mid}/restore` | `get_current_user`; floor: any role | Velaris mail message restore post. |
| PUT | `/mail/mailboxes/{mb}/quota` | `get_current_user`; floor: any role | Velaris mail mailbox quota put. |
| GET | `/mail/mailboxes/{mb}/rules` | `get_current_user`; floor: any role | Velaris mail rules get. |
| POST | `/mail/mailboxes/{mb}/rules` | `get_current_user`; floor: any role | Velaris mail rule create post. |
| POST | `/mail/mailboxes/{mb}/rules/dry-run` | `get_current_user`; floor: any role | Velaris mail rule dry run post. |
| DELETE | `/mail/mailboxes/{mb}/rules/{rid}` | `get_current_user`; floor: any role | Velaris mail rule delete delete. |
| PUT | `/mail/mailboxes/{mb}/rules/{rid}` | `get_current_user`; floor: any role | Velaris mail rule update put. |
| GET | `/mail/mailboxes/{mb}/settings` | `get_current_user`; floor: any role | Velaris mail mailbox settings get. |
| PUT | `/mail/mailboxes/{mb}/settings` | `get_current_user`; floor: any role | Velaris mail mailbox settings set put. |
| GET | `/mail/mailboxes/{mb}/submissions` | `get_current_user`; floor: any role | Velaris mail submissions get. |
| POST | `/mail/mailboxes/{mb}/sync` | `get_current_user`; floor: any role | Velaris mail sync post. |
| GET | `/mail/mailboxes/{mb}/threads/{tid}` | `get_current_user`; floor: any role | Velaris mail thread get. |
| POST | `/mail/outbox/process` | `get_current_user`; floor: any role | Velaris mail outbox process post. |
| POST | `/mail/retention/run` | `get_current_user`; floor: any role | Velaris mail retention run post. |
| GET | `/mail/settings` | `get_current_user`; floor: any role | Velaris mail settings get. |
| PUT | `/mail/settings` | `get_current_user`; floor: any role | Velaris mail settings set put. |
| GET | `/mail/settings/dkim` | `get_current_user`; floor: any role | Velaris mail dkim get. |
| GET | `/mail/submissions/{sid}` | `get_current_user`; floor: any role | Velaris mail submission get. |
| POST | `/mail/submissions/{sid}/cancel` | `get_current_user`; floor: any role | Velaris mail submission cancel post. |
| POST | `/mail/submissions/{sid}/decide` | `get_current_user`; floor: any role | Velaris mail submission decide post. |
| GET | `/model-providers` | `get_current_user`; floor: any role | Velaris providers list get. |
| POST | `/model-providers` | `get_current_user`; floor: member+ (viewer denied) | Velaris providers create post. |
| GET | `/model-providers/usage` | `get_current_user`; floor: any role | Velaris providers usage get. |
| DELETE | `/model-providers/{pid}` | `get_current_user`; floor: member+ (viewer denied) | Velaris providers delete delete. |
| PUT | `/model-providers/{pid}` | `get_current_user`; floor: member+ (viewer denied) | Velaris providers update put. |
| GET | `/model-providers/{pid}/models` | `get_current_user`; floor: any role | Velaris providers models get. |
| POST | `/model-providers/{pid}/models/refresh` | `get_current_user`; floor: member+ (viewer denied) | Velaris providers models refresh post. |
| POST | `/model-providers/{pid}/rotate` | `get_current_user`; floor: member+ (viewer denied) | Velaris providers rotate post. |
| POST | `/model-providers/{pid}/test` | `get_current_user`; floor: member+ (viewer denied) | Velaris providers test post. |
| POST | `/hr/INTERVIEW_RECORD/give_consent` | `get_current_user` | Velaris HR interview record: give consent. |
| POST | `/hr/INTERVIEW_RECORD/register_audio_track` | `get_current_user` | Velaris HR interview record: register audio track. |
| POST | `/hr/INTERVIEW_RECORD/transcribe_track` | `get_current_user` | Velaris HR interview record: transcribe track. |
| POST | `/hr/INTERVIEW_RECORD/withdraw_my_consent` | `get_current_user` | Velaris HR interview record: withdraw my consent. |
| POST | `/hr/INTERVIEW_SCHEDULER/hand_off_to_mail` | `get_current_user` | Velaris HR interview scheduler: hand off to mail. |

### `phases/p08_cicd/webhook.py`

Tags: CI/CD. Routes: 2.

| Method | Path | Auth | Summary |
|---|---|---|---|
| GET | `/ci/jobs/{job_id}` | `require_ci_auth` | Get the status of a repair job. |
| POST | `/ci/webhook` | `require_ci_auth` | Receive a CI failure webhook and trigger automated repair. |

