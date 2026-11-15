#!/usr/bin/env bash
# Fails (non-zero) on any known vulnerability in the pinned lock file.
# Run locally exactly as CI does:  bash scripts/ci/audit_deps.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
# Accepted findings (no fixed release exists). Re-check on every dependency bump; delete when fixed.
# chromadb PYSEC-2026-311/3813/3814/3815 are SERVER-mode flaws (unauthenticated HTTP API, RBAC,
# remote model repos). AetherOS uses only the embedded chromadb.PersistentClient
# (core/memory/vector_store.py, phases/p13_app_memory/task_agent.py) and never runs `chroma run`.
exec pip-audit -r requirements.lock --no-deps --disable-pip \
  --ignore-vuln PYSEC-2026-311 --ignore-vuln PYSEC-2026-3813 \
  --ignore-vuln PYSEC-2026-3814 --ignore-vuln PYSEC-2026-3815
