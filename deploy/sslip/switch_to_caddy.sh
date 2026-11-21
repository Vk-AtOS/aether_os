#!/bin/bash
# Put Caddy in front of nginx on a no-domain host (KAN-75), so per-run preview origins get certificates on demand.
# Usage (root, on the host, from the aether_os checkout): deploy/sslip/switch_to_caddy.sh <host> [acme-email]
#   host: the public name, e.g. 3-105-82-63.sslip.io
# Idempotent. Keeps the previous nginx config and rolls back to it if the new front does not answer.
set -euo pipefail
HOST="${1:?usage: switch_to_caddy.sh <host> [acme-email]}"; EMAIL="${2:-}"
cd "$(dirname "$0")/../.."
NGINX_IMG="nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10"
CADDY_IMG="caddy:2.8.4-alpine@sha256:af32e97399febea808609119bb21544d0265c58a02836576e32a2d082c262c17"
DIST=/home/aether_os/dashboard/dist
mkdir -p /srv/caddy/data /srv/caddy/config
python3 deploy/sslip/render_nginx_behind_caddy.py "$HOST" /srv/front ${EMAIL:+"$EMAIL"}

rollback() {
  echo "new front failed; restoring the previous nginx on 80/443" >&2
  docker rm -f aether-caddy >/dev/null 2>&1 || true
  docker rm -f aether-nginx >/dev/null 2>&1 || true
  docker run -d --name aether-nginx --restart unless-stopped --network host \
    -v /srv/nginx-aetheros.conf:/etc/nginx/conf.d/default.conf:ro -v $DIST:$DIST:ro \
    -v /etc/letsencrypt:/etc/letsencrypt:ro -v /var/www/certbot:/var/www/certbot:ro "$NGINX_IMG" >/dev/null
  exit 1
}

docker rm -f aether-nginx >/dev/null 2>&1 || true
docker run -d --name aether-nginx --restart unless-stopped --network host \
  -v /srv/front/nginx.conf:/etc/nginx/conf.d/default.conf:ro \
  -v /srv/front/velaris_public.conf:/etc/nginx/conf.d/velaris_public.conf:ro \
  -v /srv/front/velaris_public_proxy.conf:/etc/nginx/velaris_public_proxy.conf:ro -v $DIST:$DIST:ro "$NGINX_IMG" >/dev/null
sleep 2; docker exec aether-nginx nginx -t >/dev/null 2>&1 || rollback

docker rm -f aether-caddy >/dev/null 2>&1 || true
docker run -d --name aether-caddy --restart unless-stopped --network host \
  -v /srv/front/Caddyfile:/etc/caddy/Caddyfile:ro -v /srv/caddy/data:/data -v /srv/caddy/config:/config "$CADDY_IMG" >/dev/null

for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' "https://$HOST/api/health" || true)
  [ "$code" = 200 ] && break; sleep 4
done
[ "${code:-}" = 200 ] || rollback
# Certbot's renewal cron belongs to the old front; Caddy renews its own certificates.
rm -f /etc/cron.d/aetheros-certbot
echo "Caddy front active for $HOST (app via nginx 127.0.0.1:8080, previews on demand)"
