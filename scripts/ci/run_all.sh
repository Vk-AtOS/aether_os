#!/usr/bin/env bash
# Runs every CI check locally, in the same order and with the same commands as
# .github/workflows/ci.yml. Missing optional tools are reported, not silently skipped.
# Usage: bash scripts/ci/run_all.sh [--skip-tests]
set -uo pipefail
cd "$(dirname "$0")/../.."
fail=0
step() { echo; echo "== $1"; shift; "$@" || { echo "FAILED: $*"; fail=1; }; }
step "ruff"            ruff check . --select F,E9,B904,E401,PIE790,W605
[ -n "${DATABASE_URL:-}" ] && step "migrations" bash scripts/ci/check_migrations.sh || echo "(DATABASE_URL not set: migration check skipped)"
step "docs-vs-code" env PYTHONPATH="$(cd .. && pwd)" python3 scripts/ci/check_docs.py
step "bandit"          bandit -r core gateway orchestrator phases agents -lll -q --exclude '*/tests/*'
step "pip-audit"       bash scripts/ci/audit_deps.sh
step "gitleaks"        bash scripts/ci/secret_scan.sh
if [ "${1:-}" != "--skip-tests" ]; then
  # package must be importable as aether_os: the checkout dir is that package.
  P=$(mktemp -d); ln -sfn "$PWD" "$P/aether_os"
  step "pytest" env PYTHONPATH="$P" python3 -m pytest tests -q --timeout=300 --tb=short
fi
command -v actionlint >/dev/null && step "actionlint" actionlint || echo "(actionlint not installed: skipped)"
exit $fail
