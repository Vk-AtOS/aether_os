#!/bin/bash
# =============================================================================
# AetherOS — Staging deploy script
#
# Spins up an isolated staging stack alongside production on the same host.
# Staging uses port 8001 (API), 127.0.0.1 only (Postgres/Redis are internal) and its own
# Docker volumes prefixed with "staging_".
#
# Usage (run from repo root):
#   bash deploy/staging-deploy.sh
#
# Prerequisites:
#   - docker and docker-compose installed
#   - .env.staging exists (or .env will be copied as a starting point)
#   - npm and node installed for dashboard build
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/docker-compose.staging.yml"
ENV_FILE="$REPO_ROOT/.env.staging"
ENV_PROD="$REPO_ROOT/.env"

echo "=== AetherOS staging deploy @ $(date) ==="
echo "-> Repo root: $REPO_ROOT"

# ── Step 1: Ensure .env.staging exists ─────────────────────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "$ENV_PROD" ]]; then
        echo "WARNING: .env.staging not found — copying .env to .env.staging as a starting point."
        echo "         Review .env.staging and ensure DATABASE_URL / REDIS_URL are correct for staging."
        cp "$ENV_PROD" "$ENV_FILE"
    else
        echo "ERROR: Neither .env.staging nor .env found. Create .env.staging from .env.staging.example first."
        exit 1
    fi
else
    echo "-> .env.staging found"
fi

# DATABASE_URL / REDIS_URL are built inside docker-compose.staging.yml from POSTGRES_PASSWORD /
# REDIS_PASSWORD (required, no defaults); Postgres and Redis are not published to the host.

# Ensure ENVIRONMENT is set to staging
if grep -q "^ENVIRONMENT=" "$ENV_FILE"; then
    sed -i.bak "s|^ENVIRONMENT=.*|ENVIRONMENT=staging|" "$ENV_FILE"
else
    echo "ENVIRONMENT=staging" >> "$ENV_FILE"
fi

# Clean up sed backup files
rm -f "$ENV_FILE.bak"

# ── Step 3: Build the frontend ───────────────────────────────────────────────
echo "-> Building dashboard..."
cd "$REPO_ROOT/dashboard"
npm ci --silent
npm run build
cd "$REPO_ROOT"
echo "   Dashboard built"

# ── Step 4: Build and start Docker containers ────────────────────────────────
echo "-> Starting staging containers..."
docker-compose -f "$COMPOSE_FILE" up -d --build
echo "   Containers started"

# ── Step 5: Run Alembic migrations against staging DB ───────────────────────
echo "-> Waiting 10 seconds for containers to initialise..."
sleep 10

echo "-> Running Alembic migrations (main head)..."
docker-compose -f "$COMPOSE_FILE" exec api_staging alembic upgrade revision_merge_guardian_heads \
    || echo "WARNING: Alembic main-head migration failed — check container logs"

echo "-> Running Alembic migration (add_org_scim_token)..."
docker-compose -f "$COMPOSE_FILE" exec api_staging alembic upgrade add_org_scim_token \
    || echo "WARNING: add_org_scim_token migration failed — may already be applied"

# ── Step 6: Health check ─────────────────────────────────────────────────────
echo "-> Running health check..."
sleep 3
HEALTH=$(curl -sf http://127.0.0.1:8001/health 2>/dev/null || echo "FAILED")
if echo "$HEALTH" | grep -qE "ok|healthy|running"; then
    echo "   Health check passed: $HEALTH"
else
    echo "WARNING: Health check returned: $HEALTH"
    echo "         Check logs with: docker-compose -f docker-compose.staging.yml logs api_staging"
fi

echo ""
echo "================================================================"
echo "Staging running at http://localhost:8001"
echo ""
echo "Useful commands:"
echo "  Logs:     docker-compose -f docker-compose.staging.yml logs -f api_staging"
echo "  Status:   docker-compose -f docker-compose.staging.yml ps"
echo "  Teardown: docker-compose -f docker-compose.staging.yml down -v"
echo "================================================================"
