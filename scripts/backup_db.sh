#!/usr/bin/env bash
# AetherOS — PostgreSQL backup script
# Usage: ./scripts/backup_db.sh
# Schedule: add to crontab — 0 3 * * * /path/to/aether_os/scripts/backup_db.sh

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/aetheros}"
RETAIN_DAYS="${RETAIN_DAYS:-7}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/aetheros_$TIMESTAMP.sql.gz"

# Resolve the repo root (one level up from the scripts/ dir)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load .env if present (never fails even if absent)
ENV_FILE="$REPO_ROOT/.env"
if [ -f "$ENV_FILE" ]; then
  # Export only lines that look like KEY=VALUE (skip comments, blank lines)
  set -o allexport
  # shellcheck disable=SC1090
  source <(grep -v '^#' "$ENV_FILE" | grep -E '^[A-Za-z_][A-Za-z0-9_]*=')
  set +o allexport
fi

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL not set. Export it or add it to .env before running this script." >&2
  exit 1
fi

# Refuse to back up a SQLite URL (no pg_dump available for it)
if [[ "$DATABASE_URL" == sqlite* ]]; then
  echo "ERROR: backup_db.sh is for PostgreSQL only. DATABASE_URL appears to be SQLite." >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"

echo "==> Starting AetherOS DB backup at $(date)"
echo "    Destination : $BACKUP_FILE"
echo "    Retain days : $RETAIN_DAYS"

# Dump and gzip-compress in one pipeline
pg_dump "$DATABASE_URL" | gzip > "$BACKUP_FILE"

SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)
echo "==> Backup written: $BACKUP_FILE ($SIZE)"

# Prune backups older than RETAIN_DAYS days
PRUNED=$(find "$BACKUP_DIR" -name "aetheros_*.sql.gz" -mtime "+$RETAIN_DAYS" -print)
if [ -n "$PRUNED" ]; then
  echo "$PRUNED" | xargs rm -f
  echo "==> Pruned backups older than $RETAIN_DAYS days:"
  echo "$PRUNED" | sed 's/^/    /'
else
  echo "==> No backups to prune (all within $RETAIN_DAYS days)"
fi

echo "==> Done at $(date)"
