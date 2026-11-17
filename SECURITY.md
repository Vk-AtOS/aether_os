# Security Policy

Checked against the code at commit `e5c23fd`. Each control below names the file that implements it.
No external security audit or penetration test has been done. An external penetration test is not booked yet
(KAN-119). Nothing here is a certification: no SOC 2, ISO 27001, HIPAA or GDPR attestation exists.

## Supported Versions

The `VERSION` file says `1.0.0`. No release or support policy exists in the repository. Only the current
`main` branch is maintained.

## Reporting a Vulnerability

Do not open a public GitHub issue for a vulnerability.

Send a report to **security@aetheros.ai**. This address appears only in this file; whether the mailbox exists
and who reads it: not verified. Please include:

1. What the vulnerability is and where it is.
2. Steps to reproduce, with a minimal proof of concept if you can.
3. The impact you expect.
4. How to contact you.

No PGP key is published: the repository has no `.well-known/pgp-key.txt` (`public/` holds only `favicon.svg`,
`index.html` and `js/`), so send reports without relying on encryption.

### Response targets

These are intentions. No code or tooling enforces or measures them, and how often they were met: not measured.

| Target | Action |
|--------|--------|
| 48 hours | Acknowledge the report |
| 7 days | First assessment and severity |
| 30 days | Patch prepared (critical: faster) |
| After the patch | Disclosure agreed with the reporter |

### Scope

In scope: authentication and authorisation bypass, multi-tenant isolation failures (`org_id` leakage),
injection, XSS, SSRF, token forgery or replay, rate-limit bypass, privilege escalation, sandbox escape from
generated-code execution, secrets or personal data in logs or API responses.

Out of scope: denial of service without authentication, social engineering, physical security, vulnerabilities
in dependencies that are already public (report upstream), scanner output without a working proof of concept.

### Bug bounty

None. Valid reports may be credited in release notes if the reporter agrees.

## What the code does today

### Authentication and sessions

- JWT: RS256 when `AETHER_JWT_PRIVATE_KEY_B64` + `AETHER_JWT_PUBLIC_KEY_B64`, or the `_PATH` pair, are set
  (`gateway/auth.py:43-86`). With neither, it falls back to HS256 using `AETHER_SECRET_KEY` and logs a warning
  that this is not for production (`auth.py:88-95`). With no key at all it raises (`auth.py:97`). In RS256 mode,
  `decode_access_token` refuses HS256 tokens. Only while `AETHER_ACCEPT_LEGACY_HS256_TOKENS=1` (off by default,
  migration window for pre-RS256 sessions) does it also accept HS256 tokens signed with `AETHER_SECRET_KEY`. Whether RS256 keys are set in production: not verified.
- Access token lifetime 1 hour (`auth.py:188`). Refresh token lifetime 30 days (`auth.py:178`,
  `auth_refresh.py:35`).
- Refresh tokens are single use and grouped in families. Replaying a spent refresh token revokes the whole
  family. Logout blacklists the access token. A password change or reset invalidates the user's other tokens.
  The state lives in Redis; if Redis cannot answer, requests get 503 (fail closed)
  (`gateway/auth_refresh.py:1-16`).
- A refresh token or preview token is refused as an access token (`auth.py:240-251`).
- Passwords: bcrypt, 12 rounds (`auth.py:147-148`). Policy in `core/guardian/password_shield.py`: minimum 10
  characters, at least 3 of 4 character classes, at least 4 distinct characters, a local common-password list,
  and a Have I Been Pwned k-anonymity check that fails open when the service is unreachable. Registration also
  fails open if the shield itself errors (`gateway/routers/auth_router.py:78-79`).
- API keys: generated as `aesk_` plus random hex; stored as a SHA-256 hash, with legacy bcrypt hashes still
  verified (`auth.py:157-173`).
- MFA: TOTP through `pyotp`. Login returns `mfa_required` and a short-lived token when the user has MFA on
  (`gateway/auth_mfa.py`, `routers/auth_router.py:215-220`). MFA confirm is limited to 5 attempts per 5 minutes,
  per IP and per user, and a used code cannot be replayed (`auth_mfa.py:32-68`). An organisation can require MFA
  for owners and admins, with a grace period (`gateway/role_gate.py:86-101`; `Organisation.require_admin_mfa`).
  Whether any organisation has it on: not measured.
- SAML SSO via `python3-saml` (`gateway/auth_saml.py`): metadata, login and ACS callback endpoints, an IdP
  configuration per organisation. If `python3-saml` is not installed these return 503.
- SCIM v2: Users (`gateway/routers/scim_router.py`) and Groups (`scim_groups_router.py`) endpoints, plus
  ServiceProviderConfig, ResourceTypes and Schemas.
- Account lockout: none. Brute force is limited per client IP only (next section).

### Roles

Roles ranked in `core/policy/rules.py:22`: `viewer`, `member`, `api`, `admin`, `owner`, `superadmin`.
`gateway/role_gate.py` is called for every authenticated route: a viewer may only read, plus a short list of
self-service POSTs (`VIEWER_MAY`); `/webhooks` and `/marketplace/publish` need admin or owner. Some routes are
decided by the policy engine instead (`POLICY_GATED`).

### Rate limits

`core/rate_limiter.py`, Redis sliding windows with an in-memory fallback. Defaults, each set by an environment
variable: 5 login attempts per IP per 15 minutes, 5 registrations per IP, 5 password resets per IP, 5 concurrent
runs per organisation, 20 run starts per organisation per hour. When `REQUIRE_REDIS` is on and Redis is down,
login checks deny. Otherwise they fall back to a per-worker memory counter that is not safe with several workers.
`slowapi` is in `requirements.txt` but nothing in `gateway/` or `core/` imports it.

### Multi-tenancy

Authenticated routes take `org_id` from the validated token. The `X-Org-ID` header is read only to tag log lines
(`gateway/api_helpers.py:113-130`); it is not an enforcement check. Whether every query is scoped to `org_id`:
not verified in this review.

### Response headers

`SecurityHeadersMiddleware` (`gateway/api_helpers.py:139-199`) sets `X-Content-Type-Options`,
`X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, and a Content-Security-Policy with a
per-request script nonce. The CSP keeps `'unsafe-eval'` (for the Monaco editor) and `style-src 'unsafe-inline'`,
and allows `https://cdn.jsdelivr.net`. HSTS is sent only when `ENVIRONMENT=production`. The `/app-preview`
paths get their own headers. CORS origins come from `CORS_ORIGINS` (`gateway/api.py:130-136`).

### Cookies and CSRF

State-changing API calls use a Bearer token in the `Authorization` header. Cookies exist only for app previews
(`gateway/preview_server.py:166`, `gateway/routers/run_app_router.py:59`): `HttpOnly`, `SameSite=Lax`.
(An earlier version of this file said `SameSite=Strict`; the code says `lax`.)

### Encryption at rest

Selected columns use the `EncryptedText` type: Fernet (AES-128-CBC with HMAC-SHA256) with the key from
`AETHER_FIELD_KEY` (`core/encryption.py`). In production the key is required; elsewhere a per-process key is
used, so values do not survive a restart. Two columns use it today (the metadata reports `EncryptedText` twice;
see `DATA_MODEL.md`). Everything else, including database disks, is not encrypted by application code. Disk or
backup encryption: not verified.

### Audit ledger

`core/audit/chain.py`: one hash-linked chain per organisation plus a platform chain. Each entry stores the hash
of the previous entry and its own hash. No update or delete function exists in that module. Signed checkpoints
(`core/audit/checkpoints.py`) expose a shortened tail. On PostgreSQL, startup refuses to run unless the
database triggers that block UPDATE and DELETE on the ledger exist (`core/db.py:187-205`). Personal data in the
ledger can be erased on account or organisation deletion (`core/audit/deletion.py`).

### Generated-code sandbox

`core/sandbox/docker_backend.py`: one Docker container per command; non-root user, `--cap-drop ALL`,
`no-new-privileges`, default seccomp profile, read-only root filesystem, memory, CPU, pid and file limits, an
allow-listed environment, no network for builds and tests, a firewalled egress network for package installs.
`core/sandbox/guard.py` is a separate regex check for forbidden calls (`os.system`, `subprocess`, `exec`) and a
path check; it is a filter, not isolation. Whether the host firewall is applied on any deployed host:
not verified (`core/sandbox/isolation_probe.py` exists to check this at run time).

### Data retention

No automatic retention or purge job for run data, events or LLM records exists in the code that this review
found. Audit personal data is erased on account or organisation deletion only (`core/audit/deletion.py`).

### Secrets

Configuration comes from environment variables. The repository history is scanned by gitleaks in CI; see
`docs/CI.md` for the state of that check and `docs/security/ROTATION_RUNBOOK.md` for rotation.

### Automated security checks

Exactly what runs in CI (`.github/workflows/ci.yml`, on push to `main` and `dev` and on pull requests to `main`,
all blocking): bandit at high severity only (`-lll`) on `core gateway orchestrator phases agents`, pip-audit on
`requirements.lock` (four accepted findings, see `docs/CI.md`), gitleaks on the full git history, and
`npm audit --omit=dev --audit-level=high` for the dashboard. Semgrep does not run in CI. Bandit and a code
scanner also run on generated apps inside the pipeline (`core/security/code_scanner.py`,
`stages/s05_quality`); that is a product feature, not a check on this repository.

## Service levels

The repository contains no uptime monitor, incident process or maintenance-window code. The following were in
earlier versions of this file and are removed because nothing implements or measures them: a 99.9% uptime
target, a Sunday maintenance window, response times by priority, and the claim that `/health` returns 503 with
`"status": "maintenance"` during maintenance. `/health` always returns `{"status": "ok", ...}`
(`gateway/routers/health_router.py:34-42`). `/healthz` is a liveness check and `/readyz` returns 503 when
Postgres or Redis is degraded (`health_router.py:46-62`).
