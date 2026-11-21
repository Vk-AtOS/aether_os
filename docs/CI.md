# CI: what runs and how to run it locally (KAN-119, KAN-122)

Checked against `.github/workflows/ci.yml` and `scripts/ci/` at commit `e5c23fd`.

## Workflows

- `.github/workflows/ci.yml` ("CI"): runs on push to `main` and `dev`, and on pull requests to `main`
  (`ci.yml:3-7`). It has two jobs, `test` and `dashboard`. Every step listed below fails the job when it fails:
  no step has `continue-on-error`.
- `.github/workflows/aetheros-generate.yml` ("AetherOS Generate"): not a check. It runs when an issue gets the
  label `aetheros-generate` and also has `maintainer-approved`; it calls a configured AetherOS server and pushes
  the generated project to a new branch.
- No other workflow exists. No scheduled run exists.

## Job `test` (Python 3.11, with Redis 7 and Postgres 15 service containers)

| CI step | What it runs (`ci.yml`) | Local command | Needs |
|---------|-------------------------|---------------|-------|
| ruff | `ruff check . --select F,E9,B904,E401,PIE790,W605` | same | `pip install ruff` |
| bandit, high severity only | `bandit -r core gateway orchestrator phases agents -lll -q --exclude '*/tests/*'` (line 76) | same | bandit |
| dependency audit | `bash scripts/ci/audit_deps.sh` (pip-audit on `requirements.lock`) | same | pip-audit, network |
| secret scan, full git history | `scripts/ci/install_gitleaks.sh` then `scripts/ci/secret_scan.sh` | `bash scripts/ci/secret_scan.sh` | gitleaks (`brew install gitleaks`) |
| tests and coverage floor | `pytest tests/ --timeout=300 --tb=short -q --cov=. --cov-fail-under=$COVERAGE_FLOOR` (`COVERAGE_FLOOR=50`) | needs `PYTHONPATH` so the checkout imports as `aether_os`; see `scripts/ci/run_all.sh` | Postgres only for `AETHER_PG_TEST_URL` tests (they skip without it) |
| coverage upload | uploads `coverage.xml` as an artifact | not applicable | |

Scanners that run in CI: ruff, bandit (high severity only), pip-audit, gitleaks. Semgrep does not run in CI:
no workflow or script in the repository calls it.

## Job `dashboard` (node 20, `working-directory: dashboard`)

`npm ci --no-audit --no-fund`, `npm run lint`, `npm test`, `npm audit --omit=dev --audit-level=high`,
`npm run build`. Local: `cd dashboard && npm ci && npm run lint && npm test && npm run build`.

## Jobs added for the deploy files (KAN-102, KAN-111, KAN-122)

- `migrations`: Postgres (pgvector) service, `scripts/ci/check_migrations.sh`: one Alembic head, `scripts/db_migrate.py` on an
  empty database prints `created`, a second run prints `upgraded`, the ledger triggers exist. Local: set `DATABASE_URL` to a
  scratch database. Not covered: an upgrade from the previous release's real data.
- `container-scan`: builds the API image and runs Trivy (CRITICAL/HIGH with a fix available, blocking).
- `deploy-files`: `helm lint`, `helm template`, `bash -n` on the shell scripts, `docker compose config`.
- ruff style rules beyond the set above (line length, import order, typing modernisation: thousands of findings) are not
  enforced; a rule is added to the CI command only once it is clean.

## Not in CI

- `actionlint` (workflow syntax): only `scripts/ci/run_all.sh` runs it, and only if it is installed.
- Playwright browser specs (`npm run test:e2e`): see `docs/ci_dashboard.md`.

## Run everything locally

`bash scripts/ci/run_all.sh` (add `--skip-tests` for the fast checks).
Known difference: older copies of `run_all.sh` ran `ruff check . --select E9,F63,F7,F82`, a different rule set than CI. A local pass there does not prove the CI ruff step passes. Use the command in the table.

## Notes

- `scripts/ci/audit_deps.sh` ignores four findings with no fixed release: `PYSEC-2026-311`, `-3813`, `-3814`,
  `-3815` (chromadb server-mode flaws; the script's comment says only the embedded client is used).
- gitleaks uses a pinned, checksum-verified binary (`scripts/ci/install_gitleaks.sh`), so no `GITLEAKS_LICENSE`
  secret is needed. `.gitleaks.toml` allowlists only entries its header calls verified false positives.
  Whether the history scan passes today: not measured. Credential rotation steps:
  `docs/security/ROTATION_RUNBOOK.md`.
- Not verified from here: the workflow has never run on GitHub (services, caching and the Postgres tests need a
  real run). `COVERAGE_FLOOR=50` is a placeholder; the real coverage is not measured.
