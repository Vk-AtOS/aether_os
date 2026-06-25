#!/usr/bin/env bash
# deploy-dcsp.sh — Deploy DCSP to VPS at /home/dcsp
# Run from VPS after git pull: bash /home/aether_os/scripts/deploy-dcsp.sh
set -euo pipefail

DCSP_DIR="/home/dcsp"
REPO_DIR="/home/aether_os"

echo "=== DCSP Deploy ==="

# 1. Copy DCSP source from the aether_os repo to /home/dcsp
echo "[1/5] Syncing DCSP source..."
rsync -av --delete \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache' \
  --exclude='venv/' \
  --exclude='node_modules/' \
  --exclude='*.db' \
  --exclude='*.log' \
  --exclude='logs/' \
  "$REPO_DIR/products/dcsp/" "$DCSP_DIR/"

# 2. Ensure .env exists (never commit real .env to git)
if [ ! -f "$DCSP_DIR/.env" ]; then
  echo "[2/5] WARNING: $DCSP_DIR/.env not found. Creating from template..."
  cp "$DCSP_DIR/.env.example" "$DCSP_DIR/.env"
  echo "      EDIT $DCSP_DIR/.env with real secrets before starting."
else
  echo "[2/5] .env exists — skipping."
fi

# 3. Add DCSP_LICENSE_BYPASS to .env if not already set
if ! grep -q "DCSP_LICENSE_BYPASS" "$DCSP_DIR/.env"; then
  echo "DCSP_LICENSE_BYPASS=1" >> "$DCSP_DIR/.env"
  echo "[3/5] Added DCSP_LICENSE_BYPASS=1 to .env"
else
  echo "[3/5] DCSP_LICENSE_BYPASS already set."
fi

# 4. Build and restart via docker-compose
echo "[4/5] Building and restarting DCSP containers..."
cd "$DCSP_DIR"
docker compose pull --quiet || true
docker compose up -d --build

# 5. Wait and health check
echo "[5/5] Waiting 15s for startup..."
sleep 15
if curl -fs http://localhost:8001/health > /dev/null 2>&1; then
  echo "  DCSP: OK (port 8001)"
else
  echo "  DCSP: /health not responding — check logs:"
  docker compose logs --tail=30 app
fi

echo "=== DCSP Deploy complete ==="
