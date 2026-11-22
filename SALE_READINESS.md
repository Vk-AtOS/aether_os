# AetherOS - Sale Readiness Report

**Rewritten:** 15 Nov 2026 | **Commit measured:** `e5c23fd` (branch `r3/a_docs`, plus uncommitted doc edits)

This document replaces the 22 Jul 2026 version. That version had numbers and claims that were stale or false. It is a statement of what is in the repository and what is not proven. It is not a certification and not a warranty.

---

## What it is

AetherOS is a 12-stage pipeline (`stages/s01_intake` to `stages/s12_specialist`) that takes a plain-English requirement and writes a FastAPI backend, a React/Vite frontend, Dockerfile, CI files and Kubernetes manifests into a project folder. The code for this exists in the repo. A full end-to-end build on a real model has not been run as part of this work (see Known gaps).

---

## How these numbers were measured

The table is generated: no figure in it is typed by hand, and `python scripts/ci/repo_stats.py --check` (part of the CI step "Docs match code") fails when it drifts from the repository.

<!-- repo_stats:begin (written by `python scripts/ci/repo_stats.py --write`; do not edit by hand) -->
Computed by `python scripts/ci/repo_stats.py --write` on the working tree on top of commit `a50f9154` (2026-11-22). Counts are over git-tracked files.

| Metric | Value | How it is counted |
|---|---|---|
| Git commits | 1772 | `git rev-list --count HEAD` |
| Tracked Python files | 1360 | `git ls-files '*.py'` |
| Python lines (tracked files) | 197007 | lines of those files |
| Alembic migration files | 90 | `alembic/versions/*.py` |
| Gateway router files named `*_router.py` | 74 | `gateway/routers/*_router.py` |
| All `.py` files in `gateway/routers/` | 78 | `gateway/routers/*.py` |
| Route decorators in `gateway/routers/*.py` | 342 | lines starting `@...router.<method>(` |
| Pipeline stages | 12 | `stages/s<digit>*/` |
| Phase directories | 49 | `phases/p<digit>*/` (`phases/patterns/` is not a phase) |
| Tracked Python files under `phases/` | 402 | `git ls-files 'phases/*.py'` |
| Test files | 353 | `tests/**/test_*.py` |
| `def test_` lines in `tests/` | 2280 | lower than the collected count: parametrized tests expand |
| Frontend source files in `dashboard/src` | 221 | `.ts .tsx .js .jsx` |
| Benchmark prompt files | 10 | `benchmarks/prompts/*` |
| Python files over 600 lines | 0 | none |
| `dashboard/src/pages/ProjectView.jsx` lines | 457 | `wc -l` |
| Bare `except:` lines | 2 | `core/prompt_compiler.py:273`, `phases/p04a_backend_codegen/prompts.py:89` |
| Tests collected by pytest | 2894 | `python -m pytest --collect-only -q tests` (collection only, not a run) |
<!-- repo_stats:end -->

Last full test run: **2360 passed, 47 skipped**, the "Run tests" step of CI run 44929175212 on `main` at `9913c09`, 21 Nov 2026. That step passed; the later gitleaks full-history secret scan step of the same job failed in that run (history still holds old secrets, KAN-175). The suite was not re-run for this document, and the collected count in the table is for the tree named there, which is newer than that run.

Not measured: test coverage percent, performance numbers, uptime, number of users or customers, number of generated apps, pass rate of generated apps.

---

## Known gaps (stated plainly)

- **Nothing was run on real infrastructure in this work.** No real PostgreSQL, nginx, Helm, Docker build or real model run. The test suite uses test doubles and SQLite where it runs.
- **CI on `main` is red.** The secret scan (gitleaks) fails until the owner rotates the secrets and rewrites git history.
- **Git history still contains old secrets.** The rewrite is PENDING owner approval (KAN-175). Old JWT files and other secrets are still reachable in history. Rotation is tracked in KAN-173 and `docs/security/ROTATION_RUNBOOK.md`. A dry-run script exists at `scripts/security/history_rewrite_dryrun.sh`. Earlier versions of this document and of the due-diligence documents said history was purged. That was false.
- **No external penetration test** (KAN-119).
- **Legal documents are drafts** awaiting a lawyer (KAN-118). `IP_OWNERSHIP.md` is a declaration by the developer, not a legal opinion.
- **Generated apps have open issues** (KAN-168, KAN-169). Examples from earlier audits that were not re-checked here: password reset in generated apps stores a token but does not send email (`phases/p04a_backend_codegen/helpers.py`), and preview apps use a fixed preview secret (`core/run_app/process_manager_helpers.py`).
- **No certification.** There is no SOC 2, ISO 27001, HIPAA or GDPR certification or audit report for AetherOS. The code contains compliance checks and templates (for example `core/policy/compliance.py`, `core/compliance/`). That is not certification.
- **SAML.** SAML code exists in `gateway/auth_saml.py` with a relay-state test in `tests/test_saml_relay_state.py`. A run against a real identity provider (Okta or other) is not recorded here. SCIM payload tests exist in `tests/test_scim_provisioning.py` and use simulated payloads.
- **Not deployed here.** Whether a server is running, its uptime, and whether it is behind the code are not measured. No customers or users are claimed.
- **No recorded end-to-end benchmark.** `benchmarks/results/` is empty at this commit. A benchmark harness (`scripts/benchmark_harness.py`) and 10 prompt files exist. No baseline scores are claimed.
- **Model quality.** Output quality depends on the model configured. Earlier audits recorded that the operator environment ran on Amazon Nova models because the Anthropic path was blocked. As of 21 Nov 2026 the model is reached through an OpenAI-compatible endpoint (NVIDIA, free-tier Nemotron models) or through Bedrock (`PRIMARY_LLM`, see `.env.example`); output quality on those models is not measured here, and a Claude run waits for Bedrock access.
- **Four files are over the repo's 600-line rule** (listed above). Two are pre-approved in `CLAUDE.md` (`code_writer.py`, `factory_pipeline.py`). `phases/p05_frontend/helpers.py` (601) and `phases/p08_cicd/task_agent.py` (607) are not.
- **Earlier audit findings** (`docs/AUDIT_2026_08_08.md`, `PROJECT_STATE_AUDIT.md`) are historical. Current work is tracked in Jira project KAN. The owner register is KAN-204.

---

## What exists in the code (paths checked to exist at `e5c23fd`)

"Exists" means the file is in the repo. It does not mean it was run against real services.

| Area | Where |
|---|---|
| Gateway (FastAPI) with auth, rate limiting, audit | `gateway/`, `core/rate_limiter.py`, `core/audit/` |
| Database layer and migrations | `core/db.py`, `alembic/versions/` (79 files) |
| Multi-tenant isolation test | `tests/test_multi_tenancy.py` |
| LLM-first page writer with template fallback | `phases/p05_frontend/llm_page_writer.py` |
| Compile-error loop | `phases/p05_frontend/build_loop.py` |
| Visual critique function (earlier audit found it did not send the image; not re-checked here) | `phases/p05_frontend/preview.py` |
| Design tokens | `phases/p05_frontend/design_system.py` |
| Seed data generator | `phases/p04a_backend_codegen/crud_generator_seed.py` |
| Frontend scorer | `core/quality/dimension_scorer_frontend.py` |
| Benchmark harness | `scripts/benchmark_harness.py`, `benchmarks/prompts/` |
| Kubernetes manifests | `deploy/kubernetes/` (not applied to any cluster in this work) |
| Compliance report code | `core/compliance/pdf_report.py` |
| CI workflows | `.github/workflows/ci.yml`, `.github/workflows/aetheros-generate.yml` |

Directories that an earlier version of this document cited and that do **not** exist: `phases/p06_testing`, `phases/p08_compliance`, `phases/p09_devops`. The nearest existing ones are `phases/p07_testing`, `phases/p06_review_security`, `phases/p08_cicd`.

---

## What the operator must do before any deploy

| Action | Tracking |
|---|---|
| Approve and run the history rewrite, then force-push | KAN-175 |
| Rotate every secret that was ever in the repo or in a local env file | KAN-173, `docs/security/ROTATION_RUNBOOK.md` |
| `CREATE EXTENSION IF NOT EXISTS vector;` on PostgreSQL before the pgvector migration | not verified here |
| `alembic upgrade heads` on the target database | not run here |
| Provide a working model key | operator |

---

*Every number in this document has a command next to it. Anything not listed was not measured.*
