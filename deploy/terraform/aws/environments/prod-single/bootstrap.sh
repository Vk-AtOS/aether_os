#!/bin/bash
# Production bootstrap for the prod-single host. Run as root on the host (through SSM Session Manager / RunCommand) after
# `terraform apply`. Replace __DBHOST__ (output db_endpoint) and __DBSECRET__ (output db_password_secret_arn) first, and
# upload the two source archives to s3://<backups_bucket>/src/aether_os.tgz and velaris.tgz (git archive of main).
# Needs in Parameter Store: /<name>/admin-password and /<name>/nvidia-api-key (SecureString). Idempotent: a re-run keeps
# .env, secrets/ and the override, replaces the code and restarts. No secret value is ever printed.
set -euo pipefail
export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION:-ap-southeast-2}
N=${NAME:-aetheros-prod}
B=${BUCKET:-$N-backups-$(aws sts get-caller-identity --query Account --output text)}
until [ -f /var/run/aetheros-host-ready ]; do sleep 10; done
TOK=$(curl -s -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
IP=$(curl -s -H "X-aws-ec2-metadata-token: $TOK" http://169.254.169.254/latest/meta-data/public-ipv4)
HOST=$(echo "$IP" | tr . -).sslip.io
echo "public ip $IP host $HOST"

# ── code ──
mkdir -p /srv/logs
aws s3 cp --quiet s3://$B/src/aether_os.tgz /tmp/a.tgz; aws s3 cp --quiet s3://$B/src/velaris.tgz /tmp/v.tgz
rm -rf /srv/aether_os.new /srv/velaris; mkdir -p /srv/aether_os.new /srv/velaris
tar xzf /tmp/a.tgz -C /srv/aether_os.new; tar xzf /tmp/v.tgz -C /srv/velaris
if [ -d /srv/aether_os ]; then cp -a /srv/aether_os/.env /srv/aether_os/secrets /srv/aether_os/docker-compose.override.yml /srv/aether_os.new/ 2>/dev/null || true; rm -rf /srv/aether_os.old; mv /srv/aether_os /srv/aether_os.old; fi
mv /srv/aether_os.new /srv/aether_os; cd /srv/aether_os

# ── secrets and .env (first install only) ──
mkdir -p secrets; umask 077
[ -f secrets/velaris_identity.pem ] || openssl genpkey -algorithm ED25519 -out secrets/velaris_identity.pem
openssl pkey -in secrets/velaris_identity.pem -pubout -out secrets/velaris_identity.pub.pem
[ -f secrets/vault.key ] || openssl rand -base64 32 > secrets/vault.key
chmod 644 secrets/velaris_identity.pub.pem   # public key only; vault.key gets the Velaris user below
gp() { aws ssm get-parameter --name "/$N/$1" --with-decryption --query Parameter.Value --output text; }
GW=$(docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}')
if [ ! -f .env ]; then
cat > .env <<ENV
POSTGRES_PASSWORD=$(openssl rand -hex 24)
REDIS_PASSWORD=$(openssl rand -hex 24)
AETHER_FIELD_KEY=$(openssl rand 32 | base64 | tr '+/' '-_')
AETHER_SECRET_KEY=$(openssl rand -hex 32)
AETHER_ONE_ZT_SECRET=$(openssl rand -hex 32)
AETHER_ADMIN_EMAIL=admin@aetheros.ai
AETHER_ADMIN_PASS=$(gp admin-password)
AETHER_PREVIEW_ORIGIN=https://preview.$HOST
AETHER_PREVIEW_SECRET=$(openssl rand -hex 32)
CORS_ORIGINS=https://$HOST
FRONTEND_URL=https://$HOST/dashboard
APP_BASE_URL=https://$HOST
DOCKER_GID=$(stat -c %g /var/run/docker.sock)
VELARIS_IMAGE=velaris:prod
VELARIS_ORG=__SET_AFTER_FIRST_START__
VELARIS_API_URL=http://velaris:8730
VELARIS_API_SECRET=$(openssl rand -hex 32)
PRIMARY_LLM=openrouter
OPENROUTER_API_KEY=$(gp nvidia-api-key)
OPENROUTER_BASE_URL=https://integrate.api.nvidia.com/v1
OPENROUTER_FALLBACK_MODELS=nvidia/nemotron-3-ultra-550b-a55b,nvidia/nemotron-3.5-super-vl-120b-a12b
OPENROUTER_HEAVY_MODEL=nvidia/nemotron-3-ultra-550b-a55b
OPENROUTER_LIGHT_MODEL=nvidia/nemotron-3.5-super-vl-120b-a12b
OPENROUTER_COUNCIL_MODELS=nvidia/nemotron-3-ultra-550b-a55b,nvidia/nemotron-3.5-super-vl-120b-a12b,moonshotai/kimi-k3.1-pro,minimaxai/minimax-m3.1-flash
OPENROUTER_TIMEOUT=120
ALLOW_COMMUNITY_LLM=1
OPENROUTER_EXTRA_BODY={"chat_template_kwargs":{"enable_thinking":false}}
AETHER_SANDBOX_PUBLISH_IP=$GW
AETHER_SANDBOX_UPSTREAM_HOST=$GW
ENV
python3 - <<'PY'
pem=open("secrets/velaris_identity.pem").read().strip().replace("\n","\\n")
open(".env","a").write('VELARIS_IDENTITY_PRIVATE_KEY_PEM="%s"\n' % pem)
PY
chmod 600 .env
echo ".env created"
fi

# ── database: RDS (managed backups, 7-day point-in-time restore) instead of the compose db container ──
DBP=$(aws secretsmanager get-secret-value --secret-id '__DBSECRET__' --query SecretString --output text \
      | python3 -c 'import sys,json,urllib.parse;print(urllib.parse.quote(json.load(sys.stdin)["password"],safe=""))')
cat > docker-compose.override.yml <<YML
# Production: the API and migrations use RDS. The compose db container still starts (depends_on) but holds no data.
services:
  api:
    environment:
      DATABASE_URL: "postgresql://aether_user:$DBP@__DBHOST__:5432/aether_os"
  migrate:
    environment:
      DATABASE_URL: "postgresql://aether_user:$DBP@__DBHOST__:5432/aether_os"
YML
chmod 600 docker-compose.override.yml
unset DBP

# ── sandbox network isolation, images, stack ──
AETHER_SANDBOX_PUBLISH_IP=$GW bash core/sandbox/host_firewall.sh >/srv/logs/fw.log 2>&1 && echo "host firewall applied" || { echo "firewall FAILED"; tail -5 /srv/logs/fw.log; }
docker build -q -t aether-sandbox:1 -f core/sandbox/Dockerfile core/sandbox >/dev/null && echo "sandbox image ok"
docker build -q -t velaris:prod -f /srv/velaris/deploy/Dockerfile /srv/velaris >/dev/null && echo "velaris image ok"
# The vault key is read by the non-root Velaris user inside its container: owner-only, owned by that user, not world-readable.
chown "$(docker run --rm --entrypoint id velaris:prod -u):$(docker run --rm --entrypoint id velaris:prod -g)" secrets/vault.key
chmod 600 secrets/vault.key
UIDA=1000
mkdir -p /home/aether/.aether_os
s=$(date +%s); docker compose --profile velaris up -d --build > /srv/logs/up.log 2>&1 && echo "compose up ok in $(( $(date +%s)-s ))s" || { echo "compose up FAILED"; tail -20 /srv/logs/up.log; }
# Velaris serves exactly one AetherOS organisation and refuses every other (403 wrong_organisation), so VELARIS_ORG must be
# the id of the organisation the platform created on first start, not a made-up name (production showed the dashboard's
# Velaris pages refused, 22 Nov 2026).
if grep -q '^VELARIS_ORG=__SET_AFTER_FIRST_START__$' .env; then
  ORG=$(psql "postgresql://aether_user:$(aws secretsmanager get-secret-value --secret-id '__DBSECRET__' --query SecretString --output text | python3 -c 'import sys,json,urllib.parse;print(urllib.parse.quote(json.load(sys.stdin)["password"],safe=""))')@__DBHOST__:5432/aether_os" -tAc "select id from organisations order by created_at limit 1" 2>/dev/null)
  if [ -n "$ORG" ]; then sed -i "s/^VELARIS_ORG=.*/VELARIS_ORG=$ORG/" .env && docker compose --profile velaris up -d --no-deps velaris velaris_public >/dev/null 2>&1 && echo "VELARIS_ORG set to $ORG"; else echo "VELARIS_ORG: no organisation yet; set it in .env and restart velaris"; fi
fi
APIIMG=$(docker compose images -q api | head -1)
UIDA=$(docker run --rm --entrypoint id "$APIIMG" -u); GIDA=$(docker run --rm --entrypoint id "$APIIMG" -g)
chown -R "$UIDA:$GIDA" /home/aether/.aether_os
sleep 60
docker compose --profile velaris ps --format '{{.Service}} {{.Status}}' | tr '\n' ';'; echo
curl -s -o /dev/null -w "api healthz %{http_code}\n" http://127.0.0.1:8000/healthz || true

# ── front end: FRONT=caddy (default) or FRONT=nginx ──
# caddy: deploy/sslip (Caddy on 80/443, nginx behind it on loopback). Per-run preview hosts get certificates on demand
# and velaris.<host> serves the Velaris public app (KAN-75, KAN-128); Caddy renews its own certificates.
# nginx: the original single-nginx front with a certbot certificate for <host> and preview.<host> only; no per-run
# previews. Re-running with the default keeps a host that already runs Caddy on Caddy. Starting the old nginx on 80/443
# next to Caddy would fail.
FRONT=${FRONT:-caddy}
mkdir -p /home/aether_os/dashboard
rm -rf /home/aether_os/dashboard/dist && docker compose cp api:/srv/aether_os/dashboard/dist /home/aether_os/dashboard/dist >/dev/null
if [ "$FRONT" = caddy ]; then
  bash deploy/sslip/switch_to_caddy.sh "$HOST" || { echo "caddy front FAILED (switch_to_caddy rolled back)"; exit 1; }
else
  # ── TLS certificate (Let's Encrypt, HTTP-01, standalone on port 80 before nginx takes it) ──
  mkdir -p /etc/letsencrypt /var/www/certbot /home/aether_os/dashboard
  docker rm -f aether-nginx >/dev/null 2>&1 || true
  if [ ! -f /etc/letsencrypt/live/$HOST/fullchain.pem ]; then
    docker run --rm -p 80:80 -v /etc/letsencrypt:/etc/letsencrypt certbot/certbot:v2.11.0 certonly --standalone \
      -d "$HOST" -d "preview.$HOST" --cert-name "$HOST" --agree-tos --register-unsafely-without-email -n > /srv/logs/certbot.log 2>&1 \
      && echo "certificate issued" || { echo "certbot FAILED"; tail -15 /srv/logs/certbot.log; }
  fi
  # the preview server block expects its own certificate name; the one certificate covers both names
  mkdir -p /etc/letsencrypt/live/preview.$HOST
  ln -sf /etc/letsencrypt/live/$HOST/fullchain.pem /etc/letsencrypt/live/preview.$HOST/fullchain.pem
  ln -sf /etc/letsencrypt/live/$HOST/privkey.pem /etc/letsencrypt/live/preview.$HOST/privkey.pem

  # ── dashboard files + nginx (host network: upstream is 127.0.0.1:8000) ──
  # connect-src: same default and character filter as deploy/deploy.sh. Leaving CSP_CONNECT_SRC_PLACEHOLDER in place made
  # browsers block every dashboard API call (production, 22 Nov 2026; curl-based smoke tests cannot see it).
  CSP_CONNECT_SRC_CLEAN=$(printf '%s' "${CSP_CONNECT_SRC:-'self' https: wss: blob:}" | tr -cd "A-Za-z0-9:/.*' _-")
  sed -e "s/PREVIEW_DOMAIN_PLACEHOLDER/preview.$HOST/g" -e "s/APP_DOMAIN_PLACEHOLDER/$HOST/g" \
      -e "s|CSP_CONNECT_SRC_PLACEHOLDER|$CSP_CONNECT_SRC_CLEAN|g" deploy/nginx.conf > /srv/nginx-aetheros.conf
  grep -q PLACEHOLDER /srv/nginx-aetheros.conf && { echo "nginx config still has a PLACEHOLDER; refusing to start nginx"; exit 1; }
  docker run -d --name aether-nginx --restart unless-stopped --network host \
    -v /srv/nginx-aetheros.conf:/etc/nginx/conf.d/default.conf:ro \
    -v /home/aether_os/dashboard/dist:/home/aether_os/dashboard/dist:ro \
    -v /etc/letsencrypt:/etc/letsencrypt:ro -v /var/www/certbot:/var/www/certbot:ro nginx:1.27-alpine >/dev/null
  sleep 3; docker logs aether-nginx 2>&1 | grep -iE "emerg|error" | head -5 || true
  rpm -q cronie >/dev/null 2>&1 || dnf install -y -q cronie >/dev/null; systemctl enable --now crond >/dev/null 2>&1
  # renewal twice a day; nginx reloads to pick up a renewed certificate
  cat > /etc/cron.d/aetheros-certbot <<CRON
17 3,15 * * * root docker run --rm -v /etc/letsencrypt:/etc/letsencrypt -v /var/www/certbot:/var/www/certbot certbot/certbot:v2.11.0 renew --webroot -w /var/www/certbot -q && docker exec aether-nginx nginx -s reload
CRON
fi
curl -s -o /dev/null -w "https dashboard %{http_code}\n" https://$HOST/dashboard/ || true
curl -s -o /dev/null -w "https api %{http_code}\n" https://$HOST/api/healthz || true
echo "$HOST" > /root/public_host
