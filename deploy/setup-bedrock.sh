#!/usr/bin/env bash
# AetherOS — Enable Amazon Bedrock on the VPS
#
# Usage:
#   1. Paste your AWS credentials below (or set as env vars before running)
#   2. scp this file to the VPS or paste directly in the DO console
#   3. bash setup-bedrock.sh
#
# What this does:
#   - Adds AWS credentials + Bedrock model config to /home/aether_os/.env
#   - Runs seed_db.py to populate the marketplace (10 real templates)
#   - Restarts the aetheros service
#   - Prints verification output

set -euo pipefail

# ── EDIT THESE ────────────────────────────────────────────────────────────────
AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-REPLACE_WITH_YOUR_KEY_ID}"
AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-REPLACE_WITH_YOUR_SECRET}"
AWS_REGION="${AWS_REGION:-us-east-1}"
# ─────────────────────────────────────────────────────────────────────────────

ENV_FILE="/home/aether_os/.env"
APP_DIR="/home/aether_os"

if [[ "$AWS_ACCESS_KEY_ID" == REPLACE* ]]; then
  echo "ERROR: Set AWS_ACCESS_KEY_ID before running this script."
  echo "  export AWS_ACCESS_KEY_ID=AKIA..."
  echo "  export AWS_SECRET_ACCESS_KEY=..."
  echo "  bash setup-bedrock.sh"
  exit 1
fi

echo "==> Updating $ENV_FILE with Bedrock config..."

# Remove any existing AWS/Bedrock lines to avoid duplicates
sed -i '/^AWS_ACCESS_KEY_ID=/d'       "$ENV_FILE" 2>/dev/null || true
sed -i '/^AWS_SECRET_ACCESS_KEY=/d'   "$ENV_FILE" 2>/dev/null || true
sed -i '/^AWS_REGION=/d'              "$ENV_FILE" 2>/dev/null || true
sed -i '/^BEDROCK_ENABLED=/d'         "$ENV_FILE" 2>/dev/null || true
sed -i '/^BEDROCK_MODEL_HEAVY=/d'     "$ENV_FILE" 2>/dev/null || true
sed -i '/^BEDROCK_MODEL_LIGHT=/d'     "$ENV_FILE" 2>/dev/null || true
sed -i '/^PRIMARY_LLM=/d'             "$ENV_FILE" 2>/dev/null || true

cat >> "$ENV_FILE" <<EOF

# ── Amazon Bedrock (added by setup-bedrock.sh) ────────────────────────────────
PRIMARY_LLM=bedrock
BEDROCK_ENABLED=true
AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
AWS_REGION=${AWS_REGION}
BEDROCK_MODEL_HEAVY=us.amazon.nova-pro-v1:0
BEDROCK_MODEL_LIGHT=us.amazon.nova-lite-v1:0
EOF

echo "==> Pulling latest code..."
cd "$APP_DIR"
git pull --ff-only

echo "==> Installing dependencies..."
pip install -q -e . --no-warn-script-location

echo "==> Seeding marketplace templates..."
AETHER_ADMIN_PASS="$(grep '^AETHER_ADMIN_PASS=' "$ENV_FILE" | cut -d= -f2-)" \
DATABASE_URL="$(grep '^DATABASE_URL=' "$ENV_FILE" | cut -d= -f2-)" \
python3 seed_db.py || echo "WARN: seed_db.py failed — check logs"

echo "==> Restarting aetheros service..."
systemctl restart aetheros
sleep 5

echo "==> Service status:"
systemctl is-active aetheros && echo "Service is ACTIVE" || echo "WARN: Service is not active"

echo ""
echo "==> Verifying Bedrock connectivity..."
ACCESS_TOKEN=$(curl -s -X POST http://localhost:8001/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@aetheros.ai","password":"demo1234"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token','FAILED'))" 2>/dev/null)

if [[ "$ACCESS_TOKEN" == "FAILED" || -z "$ACCESS_TOKEN" ]]; then
  echo "WARN: Could not get access token — check service logs"
else
  BEDROCK_TEST=$(curl -s -X POST http://localhost:8001/api/settings/bedrock/test \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H 'Content-Type: application/json' \
    -d "{\"aws_access_key_id\":\"$AWS_ACCESS_KEY_ID\",\"aws_secret_access_key\":\"$AWS_SECRET_ACCESS_KEY\",\"aws_region\":\"$AWS_REGION\"}")
  echo "Bedrock test result: $BEDROCK_TEST"
fi

echo ""
echo "Done. Next steps:"
echo "  1. Visit http://139.59.87.218/ and start a new pipeline run"
echo "  2. Marketplace templates are at /api/marketplace/profiles"
echo "  3. Load test: pip install locust && locust -f tests/load/locustfile.py --host=http://139.59.87.218"
