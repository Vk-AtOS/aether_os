#!/usr/bin/env bash
# =============================================================================
# AetherOS — Zero-downtime deploy script (run on the VPS after setup_vps.sh)
#
# Usage:
#   cd /opt/aetheros
#   bash deploy/deploy.sh
# =============================================================================
set -euo pipefail
INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$INSTALL_DIR/venv/bin"
SERVICE=aetheros

echo "=== AetherOS deploy @ $(date) ==="

# 1. Pull latest code (preserve .env)
cd "$INSTALL_DIR"
git pull --ff-only

# 2. Python deps
"$VENV/pip" install -q --upgrade -r requirements.txt

# 3. Dashboard rebuild (only if source changed)
if git diff HEAD@{1} HEAD --name-only 2>/dev/null | grep -q "^dashboard/"; then
    echo "→ Rebuilding dashboard..."
    (cd dashboard && npm ci --silent && npm run build)
else
    echo "→ Dashboard unchanged, skipping rebuild"
fi

# 4. Restart service
systemctl restart "$SERVICE"
sleep 3
systemctl is-active "$SERVICE" && echo "✅ $SERVICE restarted cleanly" || {
    echo "❌ Restart failed:"
    journalctl -u "$SERVICE" -n 20 --no-pager
    exit 1
}

echo "=== Deploy done ==="
