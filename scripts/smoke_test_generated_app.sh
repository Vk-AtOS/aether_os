#!/usr/bin/env bash
# smoke_test_generated_app.sh — test a running generated AetherOS app
# Usage: ./scripts/smoke_test_generated_app.sh http://localhost:8080
#        ./scripts/smoke_test_generated_app.sh http://app-preview.example.com
set -euo pipefail

BASE_URL="${1:-http://localhost:8080}"
ADMIN_EMAIL="${2:?usage: smoke_test_generated_app.sh <url> <email> <password>}"
ADMIN_PASS="${3:?usage: smoke_test_generated_app.sh <url> <email> <password> (see preview_credentials.json)}"
PASS=0
FAIL=0

check() {
  local name="$1"
  local expected="$2"
  local actual="$3"
  if echo "$actual" | grep -q "$expected" 2>/dev/null; then
    echo "  PASS  $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  $name (expected: $expected)"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== Generated App Smoke Test: $BASE_URL ==="
echo ""

# L1: Health check
echo "[ L1 Startup ]"
R=$(curl -sf "$BASE_URL/health" 2>&1 || echo "CURL_FAIL")
check "GET /health returns 200" '"status"' "$R"

# L2: Auth
echo "[ L2 Auth ]"
LOGIN=$(curl -sf -X POST "$BASE_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASS\"}" 2>&1 || echo "CURL_FAIL")
check "POST /auth/login returns access_token" 'access_token' "$LOGIN"

TOKEN=$(echo "$LOGIN" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || echo "")

# L3: CRUD (try /items/ as fallback entity if no specific entity known)
echo "[ L3 CRUD ]"
if [ -n "$TOKEN" ]; then
  for ENTITY in items users products orders employees; do
    R=$(curl -sf -H "Authorization: Bearer $TOKEN" "$BASE_URL/$ENTITY/" 2>&1 || echo "CURL_FAIL")
    if echo "$R" | grep -qE '^\[|\{"items"'; then
      check "GET /$ENTITY/ returns list" '\[' "$R"
      # L4: Data check
      echo "[ L4 Seed data ]"
      COUNT=$(echo "$R" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else d.get('total',len(d.get('items',[]))))" 2>/dev/null || echo "0")
      if [ "$COUNT" -gt "0" ]; then
        check "Seed data present ($COUNT records)" '.' "found"
      else
        check "Seed data present (0 records)" 'non-empty' "EMPTY"
      fi
      break
    fi
  done
else
  echo "  SKIP  L3/L4 — no token (auth failed)"
  FAIL=$((FAIL + 2))
fi

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
