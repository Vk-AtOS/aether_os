#!/usr/bin/env bash
# AetherOS — Secure Redis with a password
# Reads REDIS_PASSWORD from .env; generates one if absent.
# Applies the password to the running Redis instance and persists it to redis.conf.
# Usage: bash scripts/secure_redis.sh

set -uo pipefail

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
die() { log "ERROR: $*"; exit 1; }

log "=== AetherOS Redis Security Hardening ==="

# ── Load .env ─────────────────────────────────────────────────────────────────
ENV_FILE="/home/aether_os/.env"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_ENV="$(cd "$SCRIPT_DIR/.." && pwd)/.env"

if [ -f "$ENV_FILE" ]; then
    log "Loading .env from $ENV_FILE"
    set -o allexport
    # shellcheck disable=SC1090
    source <(grep -v '^#' "$ENV_FILE" | grep -E '^[A-Za-z_][A-Za-z0-9_]*=')
    set +o allexport
elif [ -f "$LOCAL_ENV" ]; then
    ENV_FILE="$LOCAL_ENV"
    log "Loading .env from $ENV_FILE"
    set -o allexport
    # shellcheck disable=SC1090
    source <(grep -v '^#' "$ENV_FILE" | grep -E '^[A-Za-z_][A-Za-z0-9_]*=')
    set +o allexport
else
    die ".env not found at $ENV_FILE or $LOCAL_ENV"
fi

# ── Generate password if not set ──────────────────────────────────────────────
if [ -z "${REDIS_PASSWORD:-}" ]; then
    log "REDIS_PASSWORD not set — generating random 32-char password ..."
    REDIS_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null \
        || openssl rand -base64 32 | tr -d '=+/' | head -c 32)
    log "Generated password (length: ${#REDIS_PASSWORD})"

    # Append to .env
    echo "" >> "$ENV_FILE"
    echo "# Redis authentication (added by secure_redis.sh on $(date '+%Y-%m-%d'))" >> "$ENV_FILE"
    echo "REDIS_PASSWORD=${REDIS_PASSWORD}" >> "$ENV_FILE"
    log "REDIS_PASSWORD appended to $ENV_FILE"
else
    log "Using existing REDIS_PASSWORD from .env (length: ${#REDIS_PASSWORD})"
fi

# ── Verify redis-cli is available ─────────────────────────────────────────────
command -v redis-cli &>/dev/null || die "redis-cli not found — install with: apt-get install redis-tools"

# ── Apply password to running Redis instance ───────────────────────────────────
log "Applying requirepass to running Redis ..."
REDIS_SET_RESULT=$(redis-cli CONFIG SET requirepass "$REDIS_PASSWORD" 2>&1)
if [ "$REDIS_SET_RESULT" = "OK" ]; then
    log "requirepass set on running Redis: OK"
else
    # Redis may already require auth — try authenticating first
    log "Direct CONFIG SET failed ($REDIS_SET_RESULT) — checking if Redis already has a password ..."
    AUTH_RESULT=$(redis-cli -a "$REDIS_PASSWORD" CONFIG SET requirepass "$REDIS_PASSWORD" 2>&1)
    if [ "$AUTH_RESULT" = "OK" ]; then
        log "Authenticated CONFIG SET: OK (password was already set)"
    else
        die "Could not set requirepass on Redis: $AUTH_RESULT"
    fi
fi

# ── Find and update redis.conf ─────────────────────────────────────────────────
log "Locating redis.conf ..."
REDIS_DIR=$(redis-cli -a "$REDIS_PASSWORD" CONFIG GET dir 2>/dev/null | tail -1)
REDIS_CONF=""

# Try common locations
for CANDIDATE in \
    "/etc/redis/redis.conf" \
    "/etc/redis.conf" \
    "${REDIS_DIR}/redis.conf" \
    "/usr/local/etc/redis/redis.conf"; do
    if [ -f "$CANDIDATE" ]; then
        REDIS_CONF="$CANDIDATE"
        log "Found redis.conf at: $REDIS_CONF"
        break
    fi
done

if [ -n "$REDIS_CONF" ]; then
    # Backup redis.conf before modifying
    cp "$REDIS_CONF" "${REDIS_CONF}.bak.$(date +%Y%m%d_%H%M%S)"
    log "Backed up redis.conf"

    if grep -qE '^requirepass\s' "$REDIS_CONF"; then
        # Update existing requirepass line
        sed -i "s|^requirepass .*|requirepass ${REDIS_PASSWORD}|" "$REDIS_CONF"
        log "Updated existing requirepass in redis.conf"
    elif grep -qE '^#\s*requirepass\s' "$REDIS_CONF"; then
        # Uncomment and set
        sed -i "s|^#\s*requirepass .*|requirepass ${REDIS_PASSWORD}|" "$REDIS_CONF"
        log "Uncommented and set requirepass in redis.conf"
    else
        # Append at end
        echo "" >> "$REDIS_CONF"
        echo "requirepass ${REDIS_PASSWORD}" >> "$REDIS_CONF"
        log "Appended requirepass to redis.conf"
    fi

    # Also ensure bind is localhost-only for defence in depth
    if ! grep -qE '^bind 127\.0\.0\.1' "$REDIS_CONF"; then
        log "NOTE: redis.conf does not have 'bind 127.0.0.1' — consider adding it for additional security"
    fi
else
    log "WARNING: redis.conf not found in common locations — requirepass is set on running instance only."
    log "         The password will be lost on Redis restart. Add 'requirepass $REDIS_PASSWORD' to your redis.conf manually."
fi

# ── Update REDIS_URL in .env to include password ──────────────────────────────
CURRENT_REDIS_URL="${REDIS_URL:-redis://localhost:6379}"
if [[ "$CURRENT_REDIS_URL" != *"@"* ]]; then
    # No password in URL yet — inject it
    NEW_REDIS_URL="${CURRENT_REDIS_URL/redis:\/\//redis://:${REDIS_PASSWORD}@}"
    if grep -qE '^REDIS_URL=' "$ENV_FILE"; then
        sed -i "s|^REDIS_URL=.*|REDIS_URL=${NEW_REDIS_URL}|" "$ENV_FILE"
    else
        echo "REDIS_URL=${NEW_REDIS_URL}" >> "$ENV_FILE"
    fi
    log "Updated REDIS_URL in .env to include password"
fi

# ── Test: PING must return PONG ────────────────────────────────────────────────
log "Testing Redis authentication ..."
PING_RESULT=$(redis-cli -a "$REDIS_PASSWORD" PING 2>&1)
if [ "$PING_RESULT" = "PONG" ]; then
    log "Redis PING test: PONG — authentication working correctly"
else
    die "Redis PING test failed: $PING_RESULT — check requirepass config"
fi

# ── Test: unauthenticated access must be denied ───────────────────────────────
UNAUTH_RESULT=$(redis-cli PING 2>&1 || true)
if echo "$UNAUTH_RESULT" | grep -qi "NOAUTH\|Authentication"; then
    log "Unauthenticated access: correctly denied (NOAUTH)"
else
    log "WARNING: unauthenticated PING returned '$UNAUTH_RESULT' — Redis may not be enforcing auth yet"
fi

log "=== Redis Security Hardening COMPLETE ==="
echo ""
echo "Summary:"
echo "  requirepass  : set (length: ${#REDIS_PASSWORD})"
echo "  PING test    : PONG"
echo "  redis.conf   : ${REDIS_CONF:-NOT FOUND — manual update required}"
echo "  .env updated : REDIS_URL now includes password"
echo ""
echo "IMPORTANT: Restart Redis to load redis.conf changes:"
echo "  systemctl restart redis"
echo "Then restart AetherOS to pick up the updated REDIS_URL:"
echo "  systemctl restart aetheros"
exit 0
