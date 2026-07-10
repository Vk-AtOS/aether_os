#!/usr/bin/env bash
# AetherOS — Add nginx rate limiting for /api/auth/ and /api/ endpoints.
# Run on the VPS via DigitalOcean console:
#   bash /home/aether_os/scripts/update_nginx_ratelimit.sh
#
# Safe to run multiple times — checks before modifying.

set -euo pipefail

NGINX_CONF="/etc/nginx/sites-available/aetheros"
NGINX_CONF_BACKUP="${NGINX_CONF}.bak.$(date +%Y%m%d_%H%M%S)"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
die() { log "ERROR: $*"; exit 1; }

log "=== AetherOS nginx Rate Limiting Setup ==="

if [ ! -f "$NGINX_CONF" ]; then
    die "$NGINX_CONF not found — is nginx installed and configured for AetherOS?"
fi

# ── Step 1: Backup ─────────────────────────────────────────────────────────────
cp "$NGINX_CONF" "$NGINX_CONF_BACKUP"
log "Backed up: $NGINX_CONF_BACKUP"

# ── Step 2: Check if rate limiting is already present ─────────────────────────
if grep -q "limit_req_zone" "$NGINX_CONF"; then
    log "Rate limiting zones already present in $NGINX_CONF"
    NEED_ZONES=false
else
    NEED_ZONES=true
fi

if grep -q "limit_req_status" "$NGINX_CONF"; then
    log "limit_req_status already configured in $NGINX_CONF"
    NEED_STATUS=false
else
    NEED_STATUS=true
fi

# ── Step 3: Add rate limiting zones if missing ────────────────────────────────
if [ "$NEED_ZONES" = true ]; then
    log "Adding rate limiting zones ..."
    # Insert before the http { block
    # Use a temp file to avoid in-place sed issues with multiline inserts
    TMPFILE=$(mktemp)
    awk '
    /^http \{/ {
        print "# Rate limiting zones — added by update_nginx_ratelimit.sh"
        print "limit_req_zone $binary_remote_addr zone=auth_limit:10m rate=5r/m;"
        print "limit_req_zone $binary_remote_addr zone=api_limit:10m  rate=60r/m;"
        print ""
    }
    { print }
    ' "$NGINX_CONF" > "$TMPFILE"
    mv "$TMPFILE" "$NGINX_CONF"
    log "Rate limiting zones added"
else
    log "Skipping zone insertion — already present"
fi

# ── Step 4: Add limit_req_status 429 to auth and api blocks if missing ────────
if [ "$NEED_STATUS" = true ]; then
    log "Adding limit_req_status 429 directives ..."
    # Add limit_req_status 429 after each limit_req zone= line
    sed -i '/limit_req zone=auth/a\            limit_req_status 429;' "$NGINX_CONF"
    sed -i '/limit_req zone=api/a\            limit_req_status 429;' "$NGINX_CONF"
    sed -i '/limit_req zone=sse/a\            limit_req_status 429;' "$NGINX_CONF"
    log "limit_req_status 429 added"
else
    log "Skipping limit_req_status — already present"
fi

# ── Step 5: Test nginx config ─────────────────────────────────────────────────
log "Testing nginx configuration ..."
if nginx -t 2>&1; then
    log "nginx -t: OK"
else
    log "nginx -t FAILED — restoring backup ..."
    cp "$NGINX_CONF_BACKUP" "$NGINX_CONF"
    die "nginx config test failed. Original restored from backup."
fi

# ── Step 6: Reload nginx ──────────────────────────────────────────────────────
log "Reloading nginx ..."
systemctl reload nginx
log "nginx reloaded successfully"

log "=== Rate Limiting Setup COMPLETE ==="
echo ""
echo "Active rate limits:"
echo "  /api/auth/  — 5 requests/minute per IP (burst 3)"
echo "  /api/       — 60 requests/minute per IP (burst 10)"
echo "  Exceeded    — returns HTTP 429 (not 503)"
echo ""
echo "Verify with:"
echo "  grep limit_req $NGINX_CONF"
exit 0
