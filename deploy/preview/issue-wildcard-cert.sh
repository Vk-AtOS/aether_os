#!/usr/bin/env bash
# Issue (once) the wildcard certificate for the preview origin with Let's Encrypt DNS-01, and install
# the renewal hook. Run as root on the host that runs nginx. KAN-75.
#
#   PREVIEW_DOMAIN=preview.example.com CERTBOT_DNS_PLUGIN=route53 CERTBOT_EMAIL=ops@example.com \
#     bash deploy/preview/issue-wildcard-cert.sh
#
# Wildcards need DNS-01, so the host needs API access to the DNS zone (for route53: an instance role limited to
# route53:ChangeResourceRecordSets on that zone; never a long-lived key in this repo). Plugins: route53, cloudflare,
# azure, digitalocean (install the matching certbot-dns-* package first). Renewal: certbot's own systemd timer
# (certbot.timer) or the aetheros-cert-renew.timer next to this file; the deploy hook reloads nginx.
set -euo pipefail

: "${PREVIEW_DOMAIN:?PREVIEW_DOMAIN is required, e.g. preview.example.com}"
: "${CERTBOT_DNS_PLUGIN:?CERTBOT_DNS_PLUGIN is required (route53|cloudflare|azure|digitalocean)}"
: "${CERTBOT_EMAIL:?CERTBOT_EMAIL is required (expiry notices go here)}"
case "$CERTBOT_DNS_PLUGIN" in route53|cloudflare|azure|digitalocean) ;; *) echo "unsupported plugin" >&2; exit 2 ;; esac

extra=()
[[ -n "${CERTBOT_DNS_CREDENTIALS:-}" ]] && extra+=("--dns-${CERTBOT_DNS_PLUGIN}-credentials" "$CERTBOT_DNS_CREDENTIALS")

certbot certonly "--dns-${CERTBOT_DNS_PLUGIN}" "${extra[@]}" \
  --non-interactive --agree-tos -m "$CERTBOT_EMAIL" \
  --cert-name "$PREVIEW_DOMAIN" -d "$PREVIEW_DOMAIN" -d "*.$PREVIEW_DOMAIN"

install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/aetheros-reload-nginx.sh <<'HOOK'
#!/usr/bin/env bash
set -euo pipefail
nginx -t && systemctl reload nginx
HOOK
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/aetheros-reload-nginx.sh
echo "issued. Check with: python3 scripts/check_preview_origin.py https://$PREVIEW_DOMAIN"
