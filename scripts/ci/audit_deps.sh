#!/usr/bin/env bash
# Fails (non-zero) on any known vulnerability in the pinned lock file.
# Run locally exactly as CI does:  bash scripts/ci/audit_deps.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
# Accepted findings (no fixed release exists as of 2026-11-21: chromadb 1.5.9, the newest, is still affected). Re-check on every bump.
# All four are chromadb SERVER-mode flaws; AetherOS only uses the embedded chromadb.PersistentClient
# (core/memory/vector_store.py, phases/p13_app_memory/task_agent.py) and never runs `chroma run`.
# PYSEC-2026-311  (CVE-2026-45829): unauthenticated code injection via trust_remote_code model repo in the server API.
# PYSEC-2026-3813 (CVE-2026-45830): missing tenant authorization on the server API.
# PYSEC-2026-3814 (CVE-2026-45833): authenticated code injection via trust_remote_code in the server /api/v2 route.
# PYSEC-2026-3815 (CVE-2026-45831): SimpleRBACAuthorizationProvider ignores tenant/database scope (server auth provider).
exec pip-audit -r requirements.lock --no-deps --disable-pip \
  --ignore-vuln PYSEC-2026-311 --ignore-vuln PYSEC-2026-3813 \
  --ignore-vuln PYSEC-2026-3814 --ignore-vuln PYSEC-2026-3815
