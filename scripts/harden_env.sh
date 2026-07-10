#!/usr/bin/env bash
# AetherOS — Harden .env file permissions after any deploy.
# Run once after deploy to ensure .env is never world-readable.
# Usage: bash scripts/harden_env.sh
#
# This script is idempotent — safe to run multiple times.

set -euo pipefail

ENV_PATH="/home/aether_os/.env"
LOG_FILE="/var/log/aether_deploy.log"

if [ ! -f "$ENV_PATH" ]; then
    echo "WARNING: $ENV_PATH not found — skipping permission hardening" >&2
    exit 0
fi

# Set owner to aether service account if it exists
if id "aether" &>/dev/null; then
    chown aether:aether "$ENV_PATH" 2>/dev/null || true
fi

# Restrict to owner read/write only — no group, no other
chmod 600 "$ENV_PATH"

ACTUAL=$(stat -c %a "$ENV_PATH" 2>/dev/null || stat -f %Lp "$ENV_PATH" 2>/dev/null || echo "unknown")
MSG="$(date '+%Y-%m-%d %H:%M:%S'): .env permissions hardened to $ACTUAL (path: $ENV_PATH)"

echo "$MSG"

# Append to deploy log (create if absent; non-fatal if /var/log is read-only in dev)
if touch "$LOG_FILE" 2>/dev/null; then
    echo "$MSG" >> "$LOG_FILE"
fi

if [ "$ACTUAL" != "600" ]; then
    echo "ERROR: chmod 600 did not take effect — actual permissions: $ACTUAL" >&2
    exit 1
fi

echo "OK — .env is now 600 (owner-only read/write)"
exit 0
