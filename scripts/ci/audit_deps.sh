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
# starlette 0.49.3 (pinned since 22 Nov 2026 so it is audited at all; before, it was an unaudited transitive dependency).
# The fixes below exist only in starlette 1.x, which needs FastAPI 0.16x and changes route enumeration (20 test failures,
# PR #45 closed): a planned migration. Until then, each is reviewed against how AetherOS is deployed and expires with it:
# PYSEC-2026-161  (CVE-2026-48710) Host header not validated in request.url: only Caddy/nginx reach the app, and they route
#                 exact configured host names only, so the Host the app sees is always one of ours.
# PYSEC-2026-248  (CVE-2026-54282) path not validated in request.url: nginx normalises and forwards the request URI.
# PYSEC-2026-249  (CVE-2026-54283) form limits ignored for urlencoded bodies: nginx client_max_body_size + limit_req.
# PYSEC-2026-2280 (CVE-2026-48817) HTTPEndpoint getattr method lookup: AetherOS defines no HTTPEndpoint classes.
# PYSEC-2026-2281 (CVE-2026-48818) StaticFiles UNC SSRF: Windows only; the image runs Linux.
exec pip-audit -r requirements.lock --no-deps --disable-pip \
  --ignore-vuln PYSEC-2026-161 --ignore-vuln PYSEC-2026-248 --ignore-vuln PYSEC-2026-249 \
  --ignore-vuln PYSEC-2026-2280 --ignore-vuln PYSEC-2026-2281 \
  --ignore-vuln PYSEC-2026-311 --ignore-vuln PYSEC-2026-3813 \
  --ignore-vuln PYSEC-2026-3814 --ignore-vuln PYSEC-2026-3815
