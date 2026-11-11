#!/usr/bin/env bash
# AetherOS local development — one entry point.
#
#   ./scripts/local.sh check   # services, model key, imports, lint
#   ./scripts/local.sh up      # migrate DB, create local test user, start server on :8000
#   ./scripts/local.sh e2e [N] # build golden prompt N (default 0) end to end, write a report
#   ./scripts/local.sh down    # stop the local server
#
# Needs: python3.11 with requirements.txt installed, local Postgres and Redis, and
# a working model key in .env (ANTHROPIC_API_KEY, or a valid AWS_BEARER_TOKEN_BEDROCK).
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PARENT="$(dirname "$REPO")"          # the package is imported as `aether_os` from here
PY="${PYTHON:-python3.11}"
PORT="${PORT:-8000}"
LOG="$REPO/.local/gateway.log"
PIDFILE="$REPO/.local/gateway.pid"
EMAIL="local-e2e@aetheros.test"
PASSWORD="${LOCAL_E2E_PASSWORD:-LocalE2e!Pass2026}"   # local-only account, never deployed

mkdir -p "$REPO/.local" "$REPO/benchmarks/results"
set -a; . "$REPO/.env"; set +a
# Velaris is a sibling repository; the dashboard's Operations page reads it from here.
export VELARIS_HOME="${VELARIS_HOME:-$PARENT/Knackforge/velaris_knackforge}"
cd "$PARENT"

ok()   { echo "  ok    $1"; }
bad()  { echo "  FAIL  $1"; FAILED=1; }
FAILED=0

check() {
  pg_isready -q && ok "Postgres" || bad "Postgres is not running"
  [ "$(redis-cli ping 2>/dev/null)" = "PONG" ] && ok "Redis" || bad "Redis is not running"
  $PY -c "from aether_os.gateway.api import create_app" 2>/dev/null \
    && ok "gateway imports" || bad "gateway does not import (run: $PY -c 'from aether_os.gateway.api import create_app')"
  $PY -m ruff check --select F821,E9 -q "$REPO" --exclude .venv >/dev/null 2>&1 \
    && ok "no undefined names" || bad "ruff found undefined names or syntax errors"
  # One real model call. A fallback to Ollama counts as a failure: it is too weak for a build.
  out="$($PY - <<'EOF' 2>&1
import asyncio, time
from aether_os.core.llm.client import get_llm_client
# The timestamp defeats the router's response cache, so this is always a live call.
print("REPLY:", asyncio.run(get_llm_client().call(f"Request {time.time()}. Reply with exactly: PONG", task_type="summarize", max_tokens=20)))
EOF
)"
  if echo "$out" | grep -q "falling back to ollama\|Using Ollama\|hard failure\|degraded\|not configured"; then
    bad "model key rejected or missing — calls fell back to Ollama. Set ANTHROPIC_API_KEY or a valid Bedrock token in .env"
  elif echo "$out" | grep -q "REPLY:.*PONG"; then ok "model call"
  else bad "model call failed: $(echo "$out" | tail -1 | cut -c1-160)"; fi
  return $FAILED
}

up() {
  (cd "$REPO" && $PY -m alembic upgrade head) || { echo "migration failed"; exit 1; }
  (cd "$REPO" && $PY scripts/create_org.py --email "$EMAIL" --password "$PASSWORD" \
      --org-name "Local E2E" --plan enterprise --force >/dev/null 2>&1)
  psql -q "${DATABASE_URL/+asyncpg/}" -c "update users set email_verified=true where email='$EMAIL'" >/dev/null
  down
  nohup $PY -m uvicorn aether_os.gateway.api:create_app --factory --host 127.0.0.1 --port "$PORT" >"$LOG" 2>&1 &
  echo $! >"$PIDFILE"
  for _ in $(seq 1 30); do
    curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && { echo "server up on :$PORT (log: $LOG)"; return 0; }
    sleep 2
  done
  echo "server did not become healthy — see $LOG"; exit 1
}

down() {
  [ -f "$PIDFILE" ] || return 0
  pid="$(cat "$PIDFILE")"; rm -f "$PIDFILE"
  kill "$pid" 2>/dev/null || return 0
  # Wait for the old server to release the port, or `up` mistakes it for the new one.
  for _ in $(seq 1 30); do kill -0 "$pid" 2>/dev/null || return 0; sleep 0.5; done
  kill -9 "$pid" 2>/dev/null
}

e2e() {
  curl -sf "http://127.0.0.1:$PORT/health" >/dev/null || up
  report="$REPO/benchmarks/results/e2e_$(date +%Y%m%d_%H%M%S).json"
  (cd "$REPO/scripts" && $PY eval_harness.py --base-url "http://127.0.0.1:$PORT" \
      --email "$EMAIL" --password "$PASSWORD" --golden-idx "${1:-0}" \
      --timeout 2700 --output "$report")
  rc=$?
  echo "report: $report"
  return $rc
}

case "${1:-}" in
  check) check ;;
  up)    up ;;
  down)  down ;;
  e2e)   e2e "${2:-0}" ;;
  *)     sed -n 2,10p "$0"; exit 2 ;;
esac
