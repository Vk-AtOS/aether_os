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
| ruff | `ruff check . --select F,E9,B904` (line 71) | same | `pip install ruff` |
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

## Not in CI

- `actionlint` (workflow syntax): only `scripts/ci/run_all.sh` runs it, and only if it is installed.
- Playwright browser specs (`npm run test:e2e`): see `docs/ci_dashboard.md`.

## Optional CI jobs the buyer can enable (KAN-109, KAN-99)

These checks need a toolchain or infrastructure that the default CI does not have. No code is needed; add a job
that installs the tool and runs the command. Until then they are listed as unverified.

| Check | Needs | Command |
|-------|-------|---------|
| Generated Go operator compiles | Go 1.22+ | `AETHER_GO_BUILD_TEST=1 pytest tests/test_p17_generated.py` |
| Generated SAM template is valid | AWS SAM CLI | `sam validate --lint -t <generated>/template.yaml` |
| Generated Rego policy is valid | `opa` binary | `opa check <generated>/policy/*.rego` |
| Sandbox images build and live sandbox tests run | Docker daemon | `docker build -f core/sandbox/Dockerfile -t aether-sandbox:1 core/sandbox` then `pytest tests/ -m docker` (same for `Dockerfile.browser`, `Dockerfile.builder`) |
| Canary and SRE remediation on a real cluster | Kubernetes cluster (kind is enough) | `kind create cluster`, then apply the generated manifests with `kubectl apply -f` |
| Kong, NATS, Terraform output | cluster or `terraform` | `terraform validate` in the generated directory; `kubectl apply --dry-run=server` |
| Kaniko base image pinned by digest | network | follow the command in `core/sandbox/Dockerfile.builder` |

## Run everything locally

`bash scripts/ci/run_all.sh` (add `--skip-tests` for the fast checks).
Known difference: `run_all.sh:9` runs `ruff check . --select E9,F63,F7,F82`, a narrower rule set than CI
(`F,E9,B904`). A local pass there does not prove the CI ruff step passes. Use the command in the table.

## Notes

- `scripts/ci/audit_deps.sh` ignores four findings with no fixed release: `PYSEC-2026-311`, `-3813`, `-3814`,
  `-3815` (chromadb server-mode flaws; the script's comment says only the embedded client is used).
- gitleaks uses a pinned, checksum-verified binary (`scripts/ci/install_gitleaks.sh`), so no `GITLEAKS_LICENSE`
  secret is needed. `.gitleaks.toml` allowlists only entries its header calls verified false positives.
  Reviewed historic findings are baselined in `.gitleaksignore` (owner decision 22 Nov 2026, see the runbook section 0); new findings still fail. Credential rotation steps:
  `docs/security/ROTATION_RUNBOOK.md`.
- Not verified from here: the workflow has never run on GitHub (services, caching and the Postgres tests need a
  real run). `COVERAGE_FLOOR=50` is a placeholder; the real coverage is not measured.
