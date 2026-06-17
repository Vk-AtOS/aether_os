#!/usr/bin/env bash
# AetherOS smoke test — run after every VPS deploy.
# Usage: ./scripts/smoke_test.sh [base_url] [email] [password]
#
# Exit 0 = all critical endpoints healthy
# Exit 1 = one or more failures

set -uo pipefail

BASE="${1:-http://REDACTED_IP}"
EMAIL="${2:-${AETHER_ADMIN_EMAIL:-demo@aetheros.ai}}"
PASS="${3:-${AETHER_ADMIN_PASS:-demo1234}}"

PASS_COUNT=0
FAIL_COUNT=0

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "  ${GREEN}PASS${NC}  $1"; PASS_COUNT=$((PASS_COUNT+1)); }
fail() { echo -e "  ${RED}FAIL${NC}  $1  →  $2"; FAIL_COUNT=$((FAIL_COUNT+1)); }
info() { echo -e "  ${YELLOW}INFO${NC}  $1"; }

echo ""
echo "AetherOS Smoke Test — $BASE"
echo "----------------------------------------"

# ── 1. Health ─────────────────────────────────────────────────────────────────
STATUS=$(curl -sf "$BASE/health" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
if [ "$STATUS" = "ok" ]; then pass "GET /health → ok"
else fail "GET /health" "status='$STATUS'"; fi

# ── 2. Auth: login ────────────────────────────────────────────────────────────
LOGIN_RESP=$(curl -sf -X POST "$BASE/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}" 2>/dev/null || echo "{}")
TOKEN=$(echo "$LOGIN_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || echo "")
if [ -n "$TOKEN" ]; then pass "POST /auth/login → token received"
else fail "POST /auth/login" "no access_token in response"; fi

if [ -z "$TOKEN" ]; then
    echo ""
    echo "Cannot continue without auth token. Check credentials."
    exit 1
fi

AUTH="-H \"Authorization: Bearer $TOKEN\""

_get() {
    curl -sf -H "Authorization: Bearer $TOKEN" "$BASE$1" 2>/dev/null
}
_post() {
    curl -sf -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
        -d "${2:-{}}" "$BASE$1" 2>/dev/null
}

# ── 3. My orgs ────────────────────────────────────────────────────────────────
ORGS=$(_get "/api/auth/my-orgs" | python3 -c "import sys,json; d=json.load(sys.stdin); print(isinstance(d,list))" 2>/dev/null || echo "")
if [ "$ORGS" = "True" ]; then pass "GET /api/auth/my-orgs → ok"
else fail "GET /api/auth/my-orgs" "unexpected response"; fi

# ── 4. Runs list ──────────────────────────────────────────────────────────────
RUNS=$(_get "/api/factory/runs" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('items',[])))" 2>/dev/null || echo "")
if [ -n "$RUNS" ]; then pass "GET /api/factory/runs → $RUNS runs"
else fail "GET /api/factory/runs" "unexpected response"; fi

# ── 5. System metrics ─────────────────────────────────────────────────────────
METRICS=$(_get "/api/system/metrics" | python3 -c "import sys,json; d=json.load(sys.stdin); print('cpu' in d or 'error' not in d)" 2>/dev/null || echo "")
if [ "$METRICS" = "True" ]; then pass "GET /api/system/metrics → ok"
else fail "GET /api/system/metrics" "unexpected response"; fi

# ── 6. Marketplace ────────────────────────────────────────────────────────────
MKT=$(_get "/api/marketplace/profiles" | python3 -c "import sys,json; d=json.load(sys.stdin); print(isinstance(d,(list,dict)))" 2>/dev/null || echo "")
if [ "$MKT" = "True" ]; then pass "GET /api/marketplace/profiles → ok"
else fail "GET /api/marketplace/profiles" "unexpected response"; fi

# ── 7. Workspaces ─────────────────────────────────────────────────────────────
WS=$(_get "/api/workspaces" | python3 -c "import sys,json; d=json.load(sys.stdin); print(isinstance(d,(list,dict)))" 2>/dev/null || echo "")
if [ "$WS" = "True" ]; then pass "GET /api/workspaces → ok"
else fail "GET /api/workspaces" "unexpected response"; fi

# ── 8. Billing plans ──────────────────────────────────────────────────────────
BILL=$(_get "/api/billing/plans" | python3 -c "import sys,json; d=json.load(sys.stdin); print(isinstance(d,(list,dict)))" 2>/dev/null || echo "")
if [ "$BILL" = "True" ]; then pass "GET /api/billing/plans → ok"
else fail "GET /api/billing/plans" "unexpected response"; fi

# ── 10. Notifications ─────────────────────────────────────────────────────────
NOTIF=$(_get "/api/notifications" | python3 -c "import sys,json; d=json.load(sys.stdin); print(isinstance(d,(list,dict)))" 2>/dev/null || echo "")
if [ "$NOTIF" = "True" ]; then pass "GET /api/notifications → ok"
else fail "GET /api/notifications" "unexpected response"; fi

# ── 11. Memory search ─────────────────────────────────────────────────────────
MEM=$(_post "/api/memory/search" '{"query":"test","limit":1}' | python3 -c "import sys,json; d=json.load(sys.stdin); print('matches' in d)" 2>/dev/null || echo "")
if [ "$MEM" = "True" ]; then pass "POST /api/memory/search → ok"
else fail "POST /api/memory/search" "no matches key in response"; fi

# ── 12. SSE token ─────────────────────────────────────────────────────────────
# Get a recent run ID to test SSE token endpoint
RUN_ID=$(_get "/api/factory/runs" | python3 -c "import sys,json; items=json.load(sys.stdin).get('items',[]); print(items[0]['id'] if items else '')" 2>/dev/null || echo "")
if [ -n "$RUN_ID" ]; then
    SSE_TOK=$(_post "/api/factory/runs/$RUN_ID/sse-token" '{}' | python3 -c "import sys,json; print(json.load(sys.stdin).get('sse_token',''))" 2>/dev/null || echo "")
    if [ -n "$SSE_TOK" ]; then pass "POST /factory/runs/{id}/sse-token → token issued"
    else fail "POST /factory/runs/{id}/sse-token" "no token returned"; fi
else
    info "No runs found — skipping SSE token test"
fi

# ── 13. Static frontend ───────────────────────────────────────────────────────
FRONT=$(curl -so /dev/null -w "%{http_code}" "$BASE/" 2>/dev/null || echo "")
if [ "$FRONT" = "200" ]; then pass "GET / → 200 (frontend served)"
else fail "GET /" "HTTP $FRONT"; fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "----------------------------------------"
TOTAL=$((PASS_COUNT + FAIL_COUNT))
echo -e "Results: ${GREEN}$PASS_COUNT passed${NC} / ${RED}$FAIL_COUNT failed${NC} / $TOTAL total"

if [ "$FAIL_COUNT" -gt 0 ]; then
    echo -e "${RED}SMOKE TEST FAILED — do not promote this build.${NC}"
    exit 1
else
    echo -e "${GREEN}SMOKE TEST PASSED — build is healthy.${NC}"
    exit 0
fi
