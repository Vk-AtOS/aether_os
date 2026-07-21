# AetherOS — Acquisition Due Diligence
**Date:** 2026-07-22 · **HEAD:** 392df54 · **Prepared by:** AetherOS Engineering

---

## Platform Overview
AetherOS is a 12-stage agentic application factory: it accepts a plain-English product description and produces a deployable full-stack application (React + FastAPI + PostgreSQL) in 6–10 minutes.

## Codebase Metrics (measured 2026-07-22)
| Metric | Value |
|--------|-------|
| Commits | 883 |
| Python files | 9,190 |
| JS/TS files | 500 |
| Python lines | 756,428 |
| Test functions | 650 |
| Test pass rate | 647/647 (100%) |

## Architecture
- **Backend:** FastAPI (Python 3.11) + PostgreSQL 16 + Redis 7 + Alembic migrations
- **Frontend:** React 18 + Vite 5 + TypeScript + TanStack Router/Query + Tailwind CSS
- **Pipeline:** 12 stages, 35+ sub-phases, parallel wave execution (Kahn topological sort)
- **LLM stack:** Anthropic claude-sonnet-4-6 (primary) → Gemini 2.5 Pro → Ollama (local fallback); circuit-breaker with semantic cache
- **Auth:** RS256 JWT + bcrypt + SAML SSO (Okta verified) + SCIM v2 provisioning
- **Security:** Field-level Fernet encryption, audit ledger with SHA-256 hash chaining, rate limiting (slowapi)

## Generation Quality (2026-07-22 state)
- **LLM-first entity pages:** yes — `llm_page_writer.py` calls frontier model per entity page; template fallback on LLM failure; `template_debt_pct` tracked per run
- **Compile-error loop:** yes — `build_loop.py` runs tsc + vite, LLM JSON-patch fixes, up to 3 rounds
- **Design system:** yes — 21-domain structured token set (`design_system.py`)
- **Seed data:** LLM-generated domain-plausible records via `get_seed_py()`; deterministic fallback
- **Frontend scoring:** static TS/TSX analysis (type safety, a11y, correctness) via `dimension_scorer_frontend.py`

## Security Posture
- All CRITICAL and HIGH findings from §24 audit (2026-07-12) fixed and committed
- JWT exposure purged from git history (git-filter-repo, 871 commits rewritten)
- VPS IP, credentials, and demo passwords removed from all documentation
- Remaining: S2 (secret rotation) and P-series (VPS deploy steps) waiting on operator

## Known Open Items
| ID | Item | Status |
|----|------|--------|
| S2 | Rotate `.env` secrets (AWS keys, AETHER_SECRET_KEY, HMAC, SCIM token) | WAITING-ON-OPERATOR |
| P1 | `alembic upgrade heads` on VPS | WAITING-ON-OPERATOR |
| P2 | Force-push rewritten history to GitHub, then `git pull` on VPS | WAITING-ON-OPERATOR |
| P3 | Restore Anthropic payment instrument (primary LLM) | WAITING-ON-OPERATOR |
| A5 | pgvector migration (CREATE EXTENSION pgvector on VPS, then `alembic upgrade heads`) | WAITING-ON-OPERATOR |
| Q12 | Run benchmark harness to establish baseline scores | WAITING-ON-OPERATOR (needs running instance) |

## What Is Not Claimed
- Live benchmark scores (harness exists at `scripts/benchmark_harness.py`; baseline run pending)
- VPS health (SSH blocked; service restart pending after force-push)
- Razorpay → Stripe migration (deferred)
