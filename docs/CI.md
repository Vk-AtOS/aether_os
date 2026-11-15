# CI: what runs and how to run it locally (KAN-119, KAN-122)

`.github/workflows/ci.yml` has two jobs. Every step is a plain command, so you can run it on a laptop.

| CI step | Local command | Needs |
|---------|---------------|-------|
| ruff (blocking) | `ruff check . --select E9,F63,F7,F82` | `pip install ruff` |
| bandit (high severity) | `bandit -r core gateway orchestrator phases agents -lll -q --exclude '*/tests/*'` | bandit |
| dependency audit (blocking) | `bash scripts/ci/audit_deps.sh` | pip-audit, network |
| secret scan, tree + history (blocking) | `bash scripts/ci/secret_scan.sh` | gitleaks (`brew install gitleaks`) |
| K8s placeholder self-test | `pytest tests/test_k8s_placeholders.py` | |
| tests + coverage floor | see `scripts/ci/run_all.sh` (needs `PYTHONPATH` so the checkout imports as `aether_os`) | Postgres only for `AETHER_PG_TEST_URL` tests (they skip without it) |
| dashboard: install, lint, test, build | `cd dashboard && npm install && npm run lint && npm test && npm run build` | node 20 |
| workflow syntax | `actionlint` | actionlint |

Everything at once: `bash scripts/ci/run_all.sh` (add `--skip-tests` for the fast checks).

Notes
- The dependency audit reads `requirements.lock`; accepted findings with no fixed release are listed with the
  reason in `scripts/ci/audit_deps.sh` (currently only embedded-mode-irrelevant chromadb server flaws).
- gitleaks uses a pinned, checksum-verified binary (`scripts/ci/install_gitleaks.sh`), so no `GITLEAKS_LICENSE`
  secret is needed. It stays red until the leaked credentials in history are rotated and history is rewritten:
  `docs/security/ROTATION_RUNBOOK.md`.
- Not verified from here: the workflow has never run on GitHub (actionlint passes; services, caching and the
  Postgres tests need a real run). `COVERAGE_FLOOR=50` is unmeasured, adjust after the first run.
