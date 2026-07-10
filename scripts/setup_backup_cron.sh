#!/usr/bin/env bash
# AetherOS — Install nightly DB backup cron job
# Run once on the VPS to set up the cron schedule.
# Usage: bash scripts/setup_backup_cron.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_SCRIPT="$SCRIPT_DIR/db_backup.sh"
CRON_LOG="/var/log/aether_backup.log"
CRON_LINE="0 2 * * * $BACKUP_SCRIPT >> $CRON_LOG 2>&1"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Setting up AetherOS DB backup cron ..."

# Make the backup script executable
chmod +x "$BACKUP_SCRIPT"
echo "  Made executable: $BACKUP_SCRIPT"

# Ensure log file exists and is writable
touch "$CRON_LOG" 2>/dev/null || true

# Install cron job if not already present
if crontab -l 2>/dev/null | grep -qF "$BACKUP_SCRIPT"; then
    echo "  Cron job already installed — no change needed."
else
    (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
    echo "  Cron job installed: $CRON_LINE"
fi

echo ""
echo "Verification:"
crontab -l | grep "$BACKUP_SCRIPT" && echo "  OK — cron entry confirmed" || echo "  WARNING: cron entry not found after install"

echo ""
echo "Done. Backup will run nightly at 02:00."
echo "Logs will appear in: $CRON_LOG"
echo ""
echo "To test immediately (dry-run check only):"
echo "  bash $BACKUP_SCRIPT"
