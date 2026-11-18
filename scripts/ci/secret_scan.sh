#!/usr/bin/env bash
# Scans the full git history (every commit, so HEAD too) with .gitleaks.toml. Fails on any finding.
# Deliberately no directory scan: that would read untracked local files such as .env.
# Needs the gitleaks binary on PATH (CI installs a pinned, checksum-verified one).
# Findings are printed redacted. Local:  bash scripts/ci/secret_scan.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
command -v gitleaks >/dev/null || { echo "gitleaks not installed (brew install gitleaks)"; exit 2; }
gitleaks git --redact=100 --no-banner --config .gitleaks.toml .
