#!/usr/bin/env bash
# =============================================================================
# AetherOS — Zero-downtime deploy script (run on the VPS after setup_vps.sh)
#
# Usage:
#   cd /home/aether_os
#   bash deploy/deploy.sh [--domain app.example.com]
#
# First-time deploy:
#   bash deploy/setup_vps.sh
#   bash deploy/deploy.sh --domain app.example.com
# =============================================================================
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$INSTALL_DIR/venv/bin"
SERVICE=aetheros
DOMAIN=""

# Parse optional --domain flag (used to configure nginx on first deploy)
while [[ $# -gt 0 ]]; do
    case $1 in
        --domain) DOMAIN="$2"; shift 2 ;;
        *) shift ;;
    esac
done

echo "=== AetherOS deploy @ $(date) ==="
echo "→ Install dir: $INSTALL_DIR"

# 1. Pull latest code (preserve .env)
cd "$INSTALL_DIR"
git pull --ff-only

# 2. Python deps
echo "→ Installing Python dependencies..."
"$VENV/pip" install -q --upgrade pip
"$VENV/pip" install -q --upgrade -r requirements.txt

# 3. Install the aether_os package itself in editable mode.
#    This makes `from aether_os.core.*` and `from aether_os.gateway.*` work
#    correctly in all uvicorn workers regardless of the directory name on disk.
echo "→ Installing aether_os package (editable)..."
"$VENV/pip" install -q -e "$INSTALL_DIR"

# 4. Run database migrations. There is a single Alembic head: always upgrade to it
#    (this includes the ledger and field-encryption migrations; the latter needs
#    AETHER_FIELD_KEY in the environment). A failed migration must stop the deploy.
echo "→ Running database migrations..."
cd "$INSTALL_DIR"
set -a; [[ -f "$INSTALL_DIR/.env" ]] && . "$INSTALL_DIR/.env"; set +a
"$VENV/python" -m alembic upgrade head

# 5. Configure nginx domain (first deploy or when --domain is passed)
if [[ -n "$DOMAIN" ]]; then
    echo "→ Configuring nginx domain: $DOMAIN"
    NGINX_CONF=/etc/nginx/sites-available/aetheros
    if [[ -f "$NGINX_CONF" ]]; then
        sed -i -e "s/APP_DOMAIN_PLACEHOLDER/$DOMAIN/g" -e "s/PREVIEW_DOMAIN_PLACEHOLDER/${PREVIEW_DOMAIN:-preview.$DOMAIN}/g" "$NGINX_CONF"
        ln -sfn "$NGINX_CONF" /etc/nginx/sites-enabled/aetheros
        nginx -t && systemctl reload nginx || echo "⚠ nginx reload failed — check config"
    fi
fi

# 6. Dashboard rebuild (only if source changed since last deploy)
if git diff HEAD@{1} HEAD --name-only 2>/dev/null | grep -q "^dashboard/"; then
    echo "→ Rebuilding dashboard..."
    NODE_VERSION=$(node --version 2>/dev/null || echo "none")
    if [[ "$NODE_VERSION" == "none" ]]; then
        echo "⚠ Node.js not found — skipping dashboard build"
    else
        (cd dashboard && npm ci --silent && npm run build)
        echo "✅ Dashboard built"
    fi
else
    echo "→ Dashboard unchanged, skipping rebuild"
fi

# 7. Reload service (migrations ran first, minimising data-integrity window)
echo "→ Reloading $SERVICE service..."
# Use reload (SIGHUP) where uvicorn supports graceful reload; fall back to restart.
systemctl reload "$SERVICE" 2>/dev/null || systemctl restart "$SERVICE"
sleep 3
systemctl is-active "$SERVICE" && echo "✅ $SERVICE reloaded cleanly" || {
    echo "❌ Reload failed — attempting full restart..."
    systemctl restart "$SERVICE"
    sleep 3
    systemctl is-active "$SERVICE" && echo "✅ $SERVICE restarted cleanly" || {
        echo "❌ Restart also failed — last 30 log lines:"
        journalctl -u "$SERVICE" -n 30 --no-pager
        exit 1
    }
}

# 8. Health check
echo "→ Running health check..."
sleep 2
HEALTH=$(curl -sf http://127.0.0.1:8000/health 2>/dev/null || echo "FAILED")
if echo "$HEALTH" | grep -q "ok\|healthy\|running"; then
    echo "✅ Health check passed"
else
    echo "⚠ Health check returned: $HEALTH"
fi

# 8b. Velaris: one correctly signed request from this host to Velaris must be accepted (HMAC + Ed25519 end to end).
#     Skipped when Velaris is not configured here. VELARIS_SMOKE_ORG is the AetherOS organisation id Velaris serves
#     (its VELARIS_ORG). A failure stops the deploy: the dashboard's Velaris pages would not work.
if [[ -n "${VELARIS_API_URL:-}" ]]; then
    echo "→ Velaris signed smoke test..."
    : "${VELARIS_SMOKE_ORG:?VELARIS_SMOKE_ORG must be set in .env when VELARIS_API_URL is set}"
    cd "$(dirname "$INSTALL_DIR")"   # the directory that contains the aether_os package
    "$VENV/python" "$INSTALL_DIR/scripts/velaris_smoke.py" --org "$VELARIS_SMOKE_ORG" || { echo "❌ Velaris smoke test failed"; exit 1; }
    cd "$INSTALL_DIR"
fi

# 9. Refresh Guardian file-integrity baseline in Redis so new file hashes are
#    recorded as trusted. Without this, Guardian flags every deploy as file_tamper.
echo "→ Running post-deploy Guardian baseline refresh..."
bash "$INSTALL_DIR/scripts/post-deploy.sh" http://127.0.0.1:8000 || echo "⚠ post-deploy.sh failed — Guardian may alert on new file hashes"

echo "=== Deploy done @ $(date) ==="
