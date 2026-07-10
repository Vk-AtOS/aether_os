#!/usr/bin/env bash
# AetherOS — Update uvicorn worker count to match available CPU cores.
# Run on the VPS via DigitalOcean console:
#   bash /home/aether_os/scripts/update_workers.sh
#
# On a 4-vCPU box, this sets --workers 4 instead of the previous --workers 2,
# eliminating 50% CPU idle time under load.

set -euo pipefail

SERVICE_FILE="/etc/systemd/system/aetheros.service"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Updating uvicorn worker count ..."

if [ ! -f "$SERVICE_FILE" ]; then
    echo "ERROR: $SERVICE_FILE not found — is AetherOS installed as a systemd service?" >&2
    exit 1
fi

WORKERS=$(nproc)
echo "CPU cores detected : $WORKERS"

# Read current workers setting for comparison
CURRENT=$(grep -oP -- '--workers \K[0-9]+' "$SERVICE_FILE" 2>/dev/null || echo "unknown")
echo "Current workers    : $CURRENT"
echo "Target workers     : $WORKERS"

if [ "$CURRENT" = "$WORKERS" ]; then
    echo "Already set to $WORKERS workers — no change needed."
else
    # Backup before modifying
    cp "$SERVICE_FILE" "${SERVICE_FILE}.bak.$(date +%Y%m%d_%H%M%S)"
    echo "Backed up: ${SERVICE_FILE}.bak.*"

    sed -i "s/--workers [0-9]*/--workers $WORKERS/" "$SERVICE_FILE"
    echo "Updated: --workers $CURRENT → --workers $WORKERS"

    systemctl daemon-reload
    echo "systemctl daemon-reload: OK"

    systemctl restart aetheros
    echo "systemctl restart aetheros: OK"

    # Give uvicorn a moment to start all workers
    sleep 3

    STATUS=$(systemctl is-active aetheros 2>/dev/null || echo "unknown")
    echo "Service status: $STATUS"
    if [ "$STATUS" != "active" ]; then
        echo "WARNING: aetheros service is not active after restart — check: journalctl -u aetheros -n 50" >&2
        exit 1
    fi
fi

echo "Done. Uvicorn now running with $WORKERS workers."
exit 0
