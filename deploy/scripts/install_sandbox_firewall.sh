#!/usr/bin/env bash
# Install + start the persistent sandbox firewall unit (KAN-245). Run as root on the Docker host, from anywhere:
#   sudo AETHER_SANDBOX_PUBLISH_IP=172.17.0.1 bash deploy/scripts/install_sandbox_firewall.sh [/srv/aether_os]
# AETHER_SANDBOX_PUBLISH_IP must equal the value in the app's .env (docker0 gateway when the gateway runs in compose);
# when unset it is read from <repo>/.env, else the unit applies the 127.0.0.1 default.
set -euo pipefail
REPO_DIR="$(cd "${1:-$(dirname "$0")/../..}" && pwd)"
IP="${AETHER_SANDBOX_PUBLISH_IP:-}"
if [ -z "$IP" ] && [ -f "$REPO_DIR/.env" ]; then
  IP="$(grep -E '^AETHER_SANDBOX_PUBLISH_IP=' "$REPO_DIR/.env" | tail -1 | cut -d= -f2- | tr -d '"' || true)"
fi
install -d -m 755 /etc/aether
printf 'AETHER_SANDBOX_PUBLISH_IP=%s\n' "$IP" > /etc/aether/sandbox-firewall.env
chmod 644 /etc/aether/sandbox-firewall.env
sed "s#@REPO_DIR@#$REPO_DIR#g" "$REPO_DIR/deploy/systemd/aether-sandbox-firewall.service" \
  > /etc/systemd/system/aether-sandbox-firewall.service
systemctl daemon-reload
systemctl enable aether-sandbox-firewall.service
systemctl restart aether-sandbox-firewall.service
systemctl --no-pager status aether-sandbox-firewall.service | head -5
echo "sandbox firewall unit installed (publish ip: ${IP:-default 127.0.0.1})"
