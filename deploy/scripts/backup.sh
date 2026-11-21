#!/usr/bin/env bash
# =============================================================================
# AetherOS — PostgreSQL Daily Backup (C12)
#
# Usage:
#   bash backup.sh
#
# Crontab (run at 02:00 UTC daily):
#   0 2 * * * /home/aether_os/deploy/scripts/backup.sh >> /var/log/aetheros/backup.log 2>&1
#
# Env vars (set in /etc/environment or the systemd override):
#   DATABASE_URL   — full PostgreSQL connection URL
#   BACKUP_DIR     — where to store dumps (default: /var/backups/aetheros)
#   BACKUP_RETAIN  — days of backups to keep (default: 30)
#   COMPOSE_DIR    — compose deploys: the directory holding docker-compose.yml. The database is reachable only on the compose
#                    network there, so the dump runs inside the db service (DATABASE_URL is not needed).
#   CHECKPOINT_DEST — when set, deploy/scripts/backup_checkpoints.sh copies the signed ledger checkpoints there after the dump.
# =============================================================================
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/aetheros}"
BACKUP_RETAIN="${BACKUP_RETAIN:-30}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/aetheros_${TIMESTAMP}.dump"

# ── Parse DATABASE_URL ────────────────────────────────────────────────────────
COMPOSE_DIR="${COMPOSE_DIR:-}"
DB_URL="${DATABASE_URL:-}"
[[ -n "$COMPOSE_DIR" ]] && DB_URL="compose"
if [[ -z "$DB_URL" ]]; then
    # Try loading from .env
    ENV_FILE="/home/aether_os/.env"
    if [[ -f "$ENV_FILE" ]]; then
        DB_URL=$(grep -E '^DATABASE_URL=' "$ENV_FILE" | cut -d= -f2- | tr -d '"' | tr -d "'")
    fi
fi

if [[ -z "$DB_URL" ]]; then
    echo "$(date -Iseconds) ERROR: DATABASE_URL not set — skipping backup"
    exit 1
fi

if [[ "$DB_URL" != postgresql* && "$DB_URL" != compose ]]; then
    echo "$(date -Iseconds) INFO: DATABASE_URL is not PostgreSQL — nothing to back up"
    exit 0
fi

# ── Create backup dir ─────────────────────────────────────────────────────────
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

# ── Run pg_dump ───────────────────────────────────────────────────────────────
echo "$(date -Iseconds) INFO: Starting backup → $BACKUP_FILE"
# Dump to a temporary name: a failed or interrupted dump must never look like a good backup.
if [[ "$DB_URL" == compose ]]; then
    docker compose --project-directory "$COMPOSE_DIR" exec -T db \
        sh -c 'pg_dump --format=custom --compress=9 -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$BACKUP_FILE.partial"
else
    pg_dump --format=custom --compress=9 "$DB_URL" > "$BACKUP_FILE.partial"
fi
mv "$BACKUP_FILE.partial" "$BACKUP_FILE"
echo "$(date -Iseconds) INFO: Backup complete ($(du -sh "$BACKUP_FILE" | cut -f1))"

# ── Prune old backups ─────────────────────────────────────────────────────────
find "$BACKUP_DIR" -name "aetheros_*.dump" -mtime +"$BACKUP_RETAIN" -delete
REMAINING=$(find "$BACKUP_DIR" -name "aetheros_*.dump" | wc -l)
echo "$(date -Iseconds) INFO: Retention cleanup done — $REMAINING backup(s) retained"

# ── Signed ledger checkpoints, kept apart from the dump (KAN-51) ──────────────
if [[ -n "${CHECKPOINT_DEST:-}" ]]; then
    bash "$(dirname "$0")/backup_checkpoints.sh"
fi

# ── Offsite backup (requires rclone configured with remote named 'backup') ─────
# BACKUP_REMOTE: rclone destination, e.g. backup:<bucket>/db (default backup:aetheros-backups/).
BACKUP_REMOTE="${BACKUP_REMOTE:-backup:aetheros-backups/}"
if command -v rclone &>/dev/null && rclone listremotes 2>/dev/null | grep -q 'backup:'; then
    rclone copy "$BACKUP_DIR" "$BACKUP_REMOTE" --max-age 30d 2>>/var/log/aetheros/backup.log \
        && echo "Offsite backup complete" >> /var/log/aetheros/backup.log \
        || echo "Offsite backup failed (non-fatal)" >> /var/log/aetheros/backup.log
fi
