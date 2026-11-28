#!/usr/bin/env bash
# Generate the RS256 JWT signing keypair and append it to .env as AETHER_JWT_{PRIVATE,PUBLIC}_KEY_B64 (KAN-272).
# The gateway refuses to start with ENVIRONMENT=production unless these are set. Idempotent: does nothing when .env
# already has non-empty values; replaces empty `KEY=` lines. Run on the host from the repo root:
#   bash deploy/scripts/gen_jwt_keys.sh [path/to/.env]      then:  docker compose up -d api
# Rotating the keypair logs every user out (all existing tokens stop verifying).
set -euo pipefail
ENV_FILE="${1:-.env}"
[ -f "$ENV_FILE" ] || { echo "no $ENV_FILE (run from the repo root or pass its path)" >&2; exit 1; }
if grep -qE '^AETHER_JWT_PRIVATE_KEY_B64=.+' "$ENV_FILE" && grep -qE '^AETHER_JWT_PUBLIC_KEY_B64=.+' "$ENV_FILE"; then
  echo "JWT keys already set in $ENV_FILE; nothing to do"; exit 0
fi
umask 077
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
openssl genrsa -out "$TMP/priv.pem" 2048 2>/dev/null
openssl rsa -in "$TMP/priv.pem" -pubout -out "$TMP/pub.pem" 2>/dev/null
PRIV="$(base64 < "$TMP/priv.pem" | tr -d '\n')"; PUB="$(base64 < "$TMP/pub.pem" | tr -d '\n')"
grep -vE '^AETHER_JWT_(PRIVATE|PUBLIC)_KEY_B64=' "$ENV_FILE" > "$TMP/env" || true
printf 'AETHER_JWT_PRIVATE_KEY_B64=%s\nAETHER_JWT_PUBLIC_KEY_B64=%s\n' "$PRIV" "$PUB" >> "$TMP/env"
cat "$TMP/env" > "$ENV_FILE"          # keep the file's owner/mode
echo "JWT RS256 keys written to $ENV_FILE; restart the api: docker compose up -d api"
