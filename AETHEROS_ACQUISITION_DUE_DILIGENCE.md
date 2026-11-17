# AetherOS - Acquisition Due Diligence
**Rewritten:** 15 Nov 2026 | **Commit measured:** `e5c23fd` | **Prepared by:** AetherOS Engineering

This replaces the 22 Jul 2026 version, which had stale numbers and two false claims (git history purged; SAML "Okta verified"). See also `SALE_READINESS.md` for the full list of known gaps. This is a description of the repository, not a certification or warranty.

---

## Platform Overview
AetherOS is a 12-stage pipeline that takes a plain-English product description and writes a full-stack application (React, FastAPI, PostgreSQL target) into a project folder. Build time per app is not measured.

## How these numbers were measured
Measured 15 Nov 2026 at commit `e5c23fd`.

| Metric | Value | Command |
|---|---|---|
| Commits | 1237 | `git rev-list --count HEAD` |
| Tracked Python files | 1141 | `git ls-files '*.py' \| wc -l` |
| Python lines | 181935 | `git ls-files '*.py' \| xargs wc -l \| tail -1` |
| Alembic migrations | 79 | `ls alembic/versions/*.py \| wc -l` |
| Router files `*_router.py` | 72 | `ls gateway/routers/*_router.py \| wc -l` |
| Frontend source files (`dashboard/src`) | 209 | `git ls-files dashboard/src \| grep -cE "\.(tsx\|jsx\|ts\|js)$"` |
| Tests collected | 1954 | `python3.11 -m pytest --collect-only -q tests` (collection only) |
| Last full test run | 1907 passed, 47 skipped | reported by the integration run on r2/int, not re-run here |
| Coverage, performance, uptime, users | not measured | |

The earlier figures (883 commits, 9,190 Python files, 756,428 Python lines, 650 test functions, 647/647 pass) were wrong or stale and are withdrawn. How the 9,190 and 756,428 figures were produced is not known; they do not match tracked source.

## Architecture (from files in the repo)
- **Backend:** FastAPI, Python 3.11, SQLAlchemy async, Alembic. PostgreSQL via `DATABASE_URL`; SQLite for local dev (`core/db.py`). Redis is used for the message bus. Not run against real PostgreSQL or Redis in this work.
- **Frontend:** React 18 and Vite in `dashboard/`.
- **Pipeline:** 12 stages (`stages/s01` to `s12`) over 50 phase directories (`phases/p*/`).
- **LLM routing:** `core/model_router.py` and `core/model_router_providers.py` hold the provider chain, timeouts and retries. The default `PRIMARY_LLM` in code is `bedrock`; Anthropic, Gemini, OpenRouter and Ollama are added by configuration. Not run against a real model in this work.
- **Auth:** JWT, bcrypt/passlib, TOTP MFA, SCIM v2 (`gateway/routers/scim_router.py`), SAML (`gateway/auth_saml.py`).
- **Security code:** field-level Fernet encryption, hash-chained audit log (`core/audit/`), rate limiting (slowapi).

### SAML / SCIM status
SAML code exists (`gateway/auth_saml.py`, `tests/test_saml_relay_state.py`). A login against a real identity provider is not recorded here, so "Okta verified" is withdrawn. SCIM tests use simulated Okta and Entra payloads (`tests/test_scim_provisioning.py`).

## Security posture
- **Git history still contains old secrets.** The history rewrite is PENDING owner approval (KAN-175). Old JWT files and other secrets are still reachable in history. Rotation is tracked in KAN-173 and `docs/security/ROTATION_RUNBOOK.md`. A dry-run script exists at `scripts/security/history_rewrite_dryrun.sh`. The earlier statement that history was purged (git-filter-repo, 871 commits) was false for this repository state.
- CI on `main` is red because the secret scan fails until rotation and history rewrite are done.
- No external penetration test (KAN-119).
- No SOC 2, ISO 27001, HIPAA or GDPR certification exists. The code has compliance checks, not certificates.
- The earlier statement "all CRITICAL and HIGH findings fixed" is not supported by later audits (`docs/AUDIT_2026_08_08.md`) and is withdrawn. Current status is tracked in Jira project KAN; the owner register is KAN-204.
- Legal documents are drafts awaiting a lawyer (KAN-118).

## Generation quality
Code exists for: LLM-first entity pages with template fallback (`phases/p05_frontend/llm_page_writer.py`), a compile-error loop (`phases/p05_frontend/build_loop.py`), design tokens (`design_system.py`), seed data (`phases/p04a_backend_codegen/crud_generator_seed.py`), and a frontend scorer (`core/quality/dimension_scorer_frontend.py`). No benchmark scores exist: `benchmarks/results/` is empty at this commit. Generated apps have open issues (KAN-168, KAN-169).

## Known open items
| Item | Status |
|---|---|
| Rotate secrets | KAN-173, waiting on owner |
| Rewrite git history and force-push | KAN-175, waiting on owner approval |
| External penetration test | KAN-119, not done |
| Legal documents | KAN-118, drafts |
| Generated-app issues | KAN-168, KAN-169, open |
| Database extension and migrations on a real PostgreSQL | not run here |
| Benchmark baseline | not run |

## What is not claimed
- Any certification, uptime, customers, revenue or users.
- That the application has run on a real PostgreSQL, nginx, Helm, Docker build or real model in this work.
- Live benchmark scores.
