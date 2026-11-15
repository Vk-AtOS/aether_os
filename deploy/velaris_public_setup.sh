#!/usr/bin/env bash
# Owner-run, once per host: bash deploy/velaris_public_setup.sh <public-domain>
# Installs the nginx site and the systemd unit for the Velaris public app (KAN-128). Needs DNS for <public-domain>
# and a certificate first:  certbot certonly --nginx -d <public-domain>
set -euo pipefail
DOMAIN="${1:?usage: velaris_public_setup.sh <public-domain>}"
[[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || { echo "bad domain" >&2; exit 2; }
HERE="$(cd "$(dirname "$0")" && pwd)"
sed "s/VELARIS_PUBLIC_DOMAIN_PLACEHOLDER/$DOMAIN/g" "$HERE/nginx_velaris_public.conf" > /etc/nginx/sites-available/velaris-public
install -m 644 "$HERE/velaris_public_proxy.conf" /etc/nginx/velaris_public_proxy.conf
ln -sfn /etc/nginx/sites-available/velaris-public /etc/nginx/sites-enabled/velaris-public
install -m 644 "$HERE/velaris-public.service" /etc/systemd/system/velaris-public.service
nginx -t
systemctl daemon-reload
systemctl enable --now velaris-public
systemctl reload nginx
echo "Done. Verify:  bash scripts/velaris_public_smoke.sh https://$DOMAIN"
