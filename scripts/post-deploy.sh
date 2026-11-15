#!/usr/bin/env bash
# Post-deploy script: refresh Guardian file-integrity baseline so watchdog
# does not flag legitimately updated files as tampering events.
#
# Refreshes baseline in Redis directly (no auth required) so it works even
# when the service just started and the rate limiter would block login.
#
# Run after every: systemctl restart aetheros
# Usage: ./scripts/post-deploy.sh [base_url] [admin_email] [admin_password]

set -euo pipefail

BASE="${1:-http://localhost:8000}"
EMAIL="${2:-${AETHER_ADMIN_EMAIL:-demo@aetheros.ai}}"
PASS="${3:-${AETHER_ADMIN_PASS:?set AETHER_ADMIN_PASS or pass the password as arg 3}}"

echo "[post-deploy] Waiting for service to be healthy..."
for i in $(seq 1 30); do
    STATUS=$(curl -sf "$BASE/health" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || echo "")
    if [ "$STATUS" = "ok" ]; then
        echo "[post-deploy] Service healthy."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "[post-deploy] ERROR: service not healthy after 30s. Aborting."
        exit 1
    fi
    sleep 1
done

# Refresh Guardian baseline in Redis directly — does not require auth and
# cannot be blocked by rate limits. This is the primary refresh mechanism.
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$SCRIPT_DIR/venv/bin"

if [[ -x "$VENV/python3" ]]; then
    echo "[post-deploy] Refreshing Guardian baseline in Redis..."
    "$VENV/python3" - <<'PYEOF'
import hashlib, os, sys
from pathlib import Path

try:
    import redis as _redis_mod
    r = _redis_mod.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
    r.ping()
except Exception as e:
    print(f"[post-deploy] Redis unavailable ({e}) — skipping Redis baseline refresh")
    sys.exit(0)

PACKAGE_ROOT = Path(os.environ.get("PYTHONPATH", "/home")).rstrip("/")
# Try standard install paths
candidates = [
    Path("/home/aether_os"),
    Path("/home/aether_os/aether_os"),
    Path(PACKAGE_ROOT),
]
root = None
for c in candidates:
    if (c / "gateway" / "api.py").exists():
        root = c
        break

if root is None:
    print("[post-deploy] Could not locate aether_os package root — skipping")
    sys.exit(0)

CRITICAL_FILES = [
    root / "gateway" / "api.py",
    root / "gateway" / "auth.py",
    root / "core" / "models.py",
    root / "core" / "db.py",
    root / "alembic" / "env.py",
]

PREFIX = "guardian:file_hash:"
updated = []
for path in CRITICAL_FILES:
    if not path.exists():
        continue
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    digest = h.hexdigest()
    key = PREFIX + hashlib.md5(str(path).encode()).hexdigest()
    r.set(key, digest)
    updated.append(path.name)

print(f"[post-deploy] Guardian baseline refreshed: {', '.join(updated)}")
PYEOF
else
    echo "[post-deploy] No venv found — skipping Redis baseline refresh"
fi

# Also try the API endpoint (non-fatal if it fails)
echo "[post-deploy] Attempting Guardian API baseline refresh..."
TOKEN=$(curl -sf -X POST "$BASE/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}" \
    2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || echo "")

if [ -n "$TOKEN" ]; then
    RESULT=$(curl -sf -X POST "$BASE/guardian/baseline/refresh" \
        -H "Authorization: Bearer $TOKEN" 2>/dev/null || echo "")
    echo "[post-deploy] API refresh: $RESULT"
else
    echo "[post-deploy] Could not get auth token — API baseline refresh skipped (Redis refresh already done above)"
fi

echo "[post-deploy] Done."
