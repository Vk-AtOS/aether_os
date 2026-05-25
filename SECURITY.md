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

- **Authentication**: JWT (python-jose, RS256 recommended in production), passlib/bcrypt, TOTP MFA (pyotp)
- **Multi-tenancy**: Every database query is scoped to `org_id`; middleware enforces `X-Org-ID` header
- **Zero-trust execution**: Generated code runs under a restricted sandbox guard (`core/sandbox/guard.py`)
- **Rate limiting**: Sliding-window rate limiter applied to all public endpoints (`core/rate_limiter.py`)
- **Secrets management**: All secrets via environment variables; no hardcoded credentials
- **Dependency scanning**: Bandit and Semgrep run in the CI pipeline on every push
- **Audit ledger**: Append-only audit log records all pipeline events per organisation

### Disclosure Hall of Fame

Responsible reporters will be listed here with their consent after coordinated disclosure.
