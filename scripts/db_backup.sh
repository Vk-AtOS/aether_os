#!/usr/bin/env bash
# AetherOS — Nightly PostgreSQL backup to DigitalOcean Spaces (S3-compatible)
# Cron: 0 2 * * * /home/aether_os/scripts/db_backup.sh >> /var/log/aether_backup.log 2>&1
#
# Requires in .env:
#   DATABASE_URL        — postgresql+asyncpg://... or postgres://... connection string
#   DO_SPACES_KEY       — DigitalOcean Spaces access key
#   DO_SPACES_SECRET    — DigitalOcean Spaces secret key
#   DO_SPACES_BUCKET    — bucket name (e.g. aetheros-backups)
#   DO_SPACES_ENDPOINT  — endpoint URL (e.g. https://nyc3.digitaloceanspaces.com)

set -uo pipefail

# ── Helpers ────────────────────────────────────────────────────────────────────
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
die() { log "ERROR: $*"; exit 1; }

log "=== AetherOS DB Backup START ==="

# ── Load .env ─────────────────────────────────────────────────────────────────
ENV_FILE="/home/aether_os/.env"
if [ ! -f "$ENV_FILE" ]; then
    # Fallback for local dev: check repo root relative to this script
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    ENV_FILE="$(cd "$SCRIPT_DIR/.." && pwd)/.env"
fi

if [ -f "$ENV_FILE" ]; then
    log "Loading credentials from $ENV_FILE"
    set -o allexport
    # shellcheck disable=SC1090
    source <(grep -v '^#' "$ENV_FILE" | grep -E '^[A-Za-z_][A-Za-z0-9_]*=')
    set +o allexport
else
    die ".env file not found at $ENV_FILE"
fi

# ── Validate required vars ─────────────────────────────────────────────────────
[ -z "${DATABASE_URL:-}" ]       && die "DATABASE_URL is not set in .env"
[ -z "${DO_SPACES_KEY:-}" ]      && die "DO_SPACES_KEY is not set in .env"
[ -z "${DO_SPACES_SECRET:-}" ]   && die "DO_SPACES_SECRET is not set in .env"
[ -z "${DO_SPACES_BUCKET:-}" ]   && die "DO_SPACES_BUCKET is not set in .env"
[ -z "${DO_SPACES_ENDPOINT:-}" ] && die "DO_SPACES_ENDPOINT is not set in .env"

if [[ "$DATABASE_URL" == sqlite* ]]; then
    die "db_backup.sh is for PostgreSQL only. DATABASE_URL appears to be SQLite."
fi

# Strip asyncpg driver prefix so pg_dump can use it directly
# postgresql+asyncpg://user:pass@host/db  →  postgresql://user:pass@host/db
PG_URL="${DATABASE_URL/postgresql+asyncpg:\/\//postgresql://}"
PG_URL="${PG_URL/postgres+asyncpg:\/\//postgresql://}"

# ── Prepare local temp file ────────────────────────────────────────────────────
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILENAME="aether_backup_${TIMESTAMP}.dump"
BACKUP_LOCAL="/tmp/${BACKUP_FILENAME}"

log "Backup file   : $BACKUP_FILENAME"
log "Spaces bucket : $DO_SPACES_BUCKET"
log "Spaces endpoint: $DO_SPACES_ENDPOINT"

# ── Run pg_dump (-Fc = custom format, compressed) ─────────────────────────────
log "Running pg_dump -Fc ..."
if ! pg_dump -Fc "$PG_URL" -f "$BACKUP_LOCAL" 2>&1; then
    die "pg_dump failed — check DATABASE_URL and PostgreSQL connectivity"
fi

DUMP_SIZE=$(du -sh "$BACKUP_LOCAL" | cut -f1)
log "pg_dump complete: $DUMP_SIZE"

# ── Upload to DigitalOcean Spaces ─────────────────────────────────────────────
REMOTE_PATH="s3://${DO_SPACES_BUCKET}/backups/${BACKUP_FILENAME}"

upload_via_awscli() {
    AWS_ACCESS_KEY_ID="$DO_SPACES_KEY" \
    AWS_SECRET_ACCESS_KEY="$DO_SPACES_SECRET" \
    aws s3 cp "$BACKUP_LOCAL" "$REMOTE_PATH" \
        --endpoint-url "$DO_SPACES_ENDPOINT" \
        --no-progress
}

upload_via_s3cmd() {
    s3cmd put "$BACKUP_LOCAL" "$REMOTE_PATH" \
        --access_key="$DO_SPACES_KEY" \
        --secret_key="$DO_SPACES_SECRET" \
        --host="${DO_SPACES_ENDPOINT#https://}" \
        --host-bucket="%(bucket)s.${DO_SPACES_ENDPOINT#https://}" \
        --ssl
}

log "Uploading to Spaces: $REMOTE_PATH"
UPLOADED=false

if command -v aws &>/dev/null; then
    log "Using aws s3 cp ..."
    if upload_via_awscli; then
        UPLOADED=true
        log "Upload via awscli: SUCCESS"
    else
        log "awscli upload failed — trying s3cmd ..."
    fi
fi

if [ "$UPLOADED" = false ] && command -v s3cmd &>/dev/null; then
    log "Using s3cmd ..."
    if upload_via_s3cmd; then
        UPLOADED=true
        log "Upload via s3cmd: SUCCESS"
    else
        log "s3cmd upload failed"
    fi
fi

if [ "$UPLOADED" = false ]; then
    rm -f "$BACKUP_LOCAL"
    die "Upload failed — neither awscli nor s3cmd succeeded. Install one with: apt-get install awscli  OR  pip install s3cmd"
fi

# ── Remove local temp file after successful upload ────────────────────────────
rm -f "$BACKUP_LOCAL"
log "Local temp file removed: $BACKUP_LOCAL"

# ── Prune backups older than 7 days from Spaces ───────────────────────────────
log "Pruning backups older than 7 days from Spaces ..."
CUTOFF=$(date -d "7 days ago" +%Y%m%d 2>/dev/null || date -v-7d +%Y%m%d 2>/dev/null || echo "")

if [ -n "$CUTOFF" ]; then
    if command -v aws &>/dev/null; then
        # List objects in backups/ prefix and delete old ones
        AWS_ACCESS_KEY_ID="$DO_SPACES_KEY" \
        AWS_SECRET_ACCESS_KEY="$DO_SPACES_SECRET" \
        aws s3 ls "s3://${DO_SPACES_BUCKET}/backups/" \
            --endpoint-url "$DO_SPACES_ENDPOINT" 2>/dev/null \
        | awk '{print $4}' \
        | grep '^aether_backup_' \
        | while read -r fname; do
            # Extract date portion: aether_backup_YYYYMMDD_HHMMSS.dump
            fdate=$(echo "$fname" | grep -oE '[0-9]{8}' | head -1)
            if [ -n "$fdate" ] && [ "$fdate" -lt "$CUTOFF" ]; then
                log "Deleting old backup: $fname (date: $fdate < cutoff: $CUTOFF)"
                AWS_ACCESS_KEY_ID="$DO_SPACES_KEY" \
                AWS_SECRET_ACCESS_KEY="$DO_SPACES_SECRET" \
                aws s3 rm "s3://${DO_SPACES_BUCKET}/backups/$fname" \
                    --endpoint-url "$DO_SPACES_ENDPOINT" 2>&1 || \
                    log "WARNING: failed to delete $fname from Spaces"
            fi
        done
    elif command -v s3cmd &>/dev/null; then
        s3cmd ls "s3://${DO_SPACES_BUCKET}/backups/" \
            --access_key="$DO_SPACES_KEY" \
            --secret_key="$DO_SPACES_SECRET" \
            --host="${DO_SPACES_ENDPOINT#https://}" \
            --host-bucket="%(bucket)s.${DO_SPACES_ENDPOINT#https://}" \
            --ssl 2>/dev/null \
        | awk '{print $4}' \
        | grep 'aether_backup_' \
        | while read -r s3path; do
            fname=$(basename "$s3path")
            fdate=$(echo "$fname" | grep -oE '[0-9]{8}' | head -1)
            if [ -n "$fdate" ] && [ "$fdate" -lt "$CUTOFF" ]; then
                log "Deleting old backup: $fname"
                s3cmd del "$s3path" \
                    --access_key="$DO_SPACES_KEY" \
                    --secret_key="$DO_SPACES_SECRET" \
                    --host="${DO_SPACES_ENDPOINT#https://}" \
                    --host-bucket="%(bucket)s.${DO_SPACES_ENDPOINT#https://}" \
                    --ssl 2>&1 || \
                    log "WARNING: failed to delete $s3path"
            fi
        done
    fi
    log "Prune complete (cutoff date: $CUTOFF)"
else
    log "WARNING: could not determine cutoff date — skipping prune"
fi

log "=== AetherOS DB Backup DONE ==="
exit 0
