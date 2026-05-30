#!/usr/bin/env bash
# Post-deploy script: refresh Guardian file-integrity baseline so watchdog
# does not flag legitimately updated files as tampering events.
#
# Run after every: systemctl restart aetheros
# Usage: ./scripts/post-deploy.sh [base_url] [admin_email] [admin_password]

set -euo pipefail

BASE="${1:-http://localhost:8000}"
EMAIL="${2:-${AETHER_ADMIN_EMAIL:-demo@aetheros.ai}}"
PASS="${3:-${AETHER_ADMIN_PASS:-demo1234}}"

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

echo "[post-deploy] Obtaining admin token..."
TOKEN=$(curl -sf -X POST "$BASE/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

if [ -z "$TOKEN" ]; then
    echo "[post-deploy] ERROR: could not obtain token. Check credentials."
    exit 1
fi

echo "[post-deploy] Refreshing Guardian baseline..."
RESULT=$(curl -sf -X POST "$BASE/guardian/baseline/refresh" \
    -H "Authorization: Bearer $TOKEN")
echo "[post-deploy] $RESULT"
echo "[post-deploy] Done."
