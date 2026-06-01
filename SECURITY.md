# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | Yes (current)      |

## Reporting a Vulnerability

AetherOS takes security seriously. If you discover a security vulnerability, please follow responsible disclosure practices and **do not** create a public GitHub issue.

### How to Report

Send an email to **security@aetheros.ai** with the following information:

1. **Description** of the vulnerability (what it is and where it exists)
2. **Steps to reproduce** — include a minimal proof-of-concept if possible
3. **Impact assessment** — what could an attacker achieve by exploiting this?
4. **Your contact information** so we can coordinate disclosure

Encrypt sensitive reports using our PGP key (available at `https://aetheros.ai/.well-known/pgp-key.txt`).

### What to Expect

| Timeline          | Action                                                         |
|-------------------|----------------------------------------------------------------|
| Within 48 hours   | Acknowledgement of your report                                 |
| Within 7 days     | Initial assessment and severity rating                         |
| Within 30 days    | Patch developed and staged for release (critical: faster)      |
| Upon patch release| Public disclosure coordinated with reporter                    |

We follow [Coordinated Vulnerability Disclosure (CVD)](https://resources.sei.cmu.edu/asset_files/SpecialReport/2017_003_001_503340.pdf). We ask that you allow us to remediate before any public disclosure.

### Scope

**In scope:**
- Authentication and authorisation bypasses
- Multi-tenant data isolation failures (`org_id` leakage)
- SQL injection, XSS, SSRF, CSRF
- JWT token forgery or replay
- Rate-limit bypass
- Privilege escalation
- Sandbox escape (generated-code execution)
- PII/secrets exposure in logs or API responses

**Out of scope:**
- Denial-of-service via resource exhaustion without authentication
- Social engineering
- Physical security
- Vulnerabilities in dependencies that are already publicly disclosed (report to the upstream project)
- Findings from automated scanners without a working proof-of-concept

### Bug Bounty

We currently operate a good-faith acknowledgement programme. Reporters of valid critical or high-severity vulnerabilities will be credited in our release notes (unless they prefer anonymity). A formal bounty programme will be announced when the product reaches general availability.

### Security Architecture Overview

- **Authentication**: JWT RS256 (RSA-2048 asymmetric signing; HS256 legacy fallback with deprecation warning), passlib/bcrypt, TOTP MFA (pyotp)
- **Multi-tenancy**: Every database query is scoped to `org_id`; middleware enforces `X-Org-ID` header
- **Zero-trust execution**: Generated code runs under a restricted sandbox guard (`core/sandbox/guard.py`)
- **Rate limiting**: Sliding-window rate limiter applied to all public endpoints (`core/rate_limiter.py`)
- **Secrets management**: All secrets via environment variables; no hardcoded credentials
- **Dependency scanning**: Bandit and Semgrep run in the CI pipeline on every push
- **Audit ledger**: Append-only audit log records all pipeline events per organisation
- **CSRF**: Not applicable — all state-changing endpoints require a `Bearer` token in the `Authorization` header. The API sets `SameSite=Strict` on any cookies and does not rely on cookie-based session auth. If cookie auth is ever added, CSRF tokens must be introduced before enabling it.

### Disclosure Hall of Fame

Responsible reporters will be listed here with their consent after coordinated disclosure.

---

## Service Level Agreement

### Uptime Target

AetherOS targets **99.9% monthly uptime** for the production service, measured as:

```
Uptime % = (total minutes in month − downtime minutes) / total minutes × 100
```

Scheduled maintenance windows are excluded from downtime calculations (see below).  
99.9% monthly availability allows a maximum of approximately **43.8 minutes of unplanned downtime per month**.

### Planned Maintenance Window

- **Window:** Sundays 02:00–04:00 UTC (2-hour maximum)
- **Notice:** At least 48 hours in advance via the GitHub repository (pinned issue or release note) and, where applicable, in-app notification
- **Frequency:** No more than twice per calendar month
- **During maintenance:** The `/health` endpoint returns HTTP 503 with `"status": "maintenance"`; all other endpoints are suspended

### Incident Response Times

| Priority | Condition | First Response | Target Resolution |
|---|---|---|---|
| P1 — Critical | Service completely unavailable (all API endpoints returning 5xx or no response) | < 1 hour | < 4 hours |
| P2 — Degraded | Core functionality impaired (pipeline runs failing, auth intermittent) | < 4 hours | < 24 hours |
| P3 — Minor | Non-critical feature broken, cosmetic issue, slow response | < 24 hours | < 72 hours |

Response times are measured from the moment an incident is reported or detected by automated monitoring, whichever is earlier.

### Support Channel

Report incidents or service issues via:

1. **GitHub Issues** — open an issue tagged `incident` in the AetherOS repository
2. **Security email** — **security@aetheros.ai** for incidents with a security component (see *Reporting a Vulnerability* above)

### SLA Exclusions

The uptime SLA does not apply during:

- **Force majeure** — natural disasters, government actions, civil unrest, or any other event outside AetherOS's reasonable control
- **Third-party provider outages** — degradation or unavailability of upstream services including Anthropic API, OpenAI API, Google Gemini API, OpenRouter, GitHub, DigitalOcean infrastructure, or Cloudflare CDN
- **Customer-caused incidents** — outages attributable to misconfiguration by the customer, abuse of the API beyond documented rate limits, or intentional load injection
- **Scheduled maintenance windows** — as described above, with required 48-hour notice
- **Security incident response** — brief unavailability required to contain an active security breach (e.g. emergency credential rotation, firewall rule changes)
