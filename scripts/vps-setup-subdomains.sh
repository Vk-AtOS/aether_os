#!/usr/bin/env bash
# vps-setup-subdomains.sh
# Run ONCE on the VPS to configure nginx + SSL for app.vkatos.com.
# Prerequisites: DNS A record for app.vkatos.com must already point to this server.
set -euo pipefail

REPO_DIR="/home/aether_os"

echo "=== VPS Subdomain Setup ==="

# 1. Install certbot if not present
if ! command -v certbot &>/dev/null; then
  echo "[1/5] Installing certbot..."
  apt-get install -y certbot python3-certbot-nginx
else
  echo "[1/5] certbot already installed."
fi

# 2. Copy nginx config
echo "[2/5] Installing nginx config..."
cp "$REPO_DIR/scripts/nginx/app.vkatos.com.conf" /etc/nginx/sites-available/app.vkatos.com
ln -sf /etc/nginx/sites-available/app.vkatos.com /etc/nginx/sites-enabled/app.vkatos.com

# 3. Temporarily allow HTTP-only so certbot can do its challenge
echo "[3/5] Creating temp HTTP config for certbot challenge..."
cat > /etc/nginx/sites-available/app.vkatos.com.tmp <<'EOF'
server { listen 80; server_name app.vkatos.com; location / { proxy_pass http://127.0.0.1:8000; } }
EOF
cp /etc/nginx/sites-available/app.vkatos.com.tmp /etc/nginx/sites-enabled/app.vkatos.com
nginx -t && systemctl reload nginx

# 4. Obtain SSL cert
echo "[4/5] Obtaining SSL certificate..."
certbot certonly --nginx -d app.vkatos.com --non-interactive --agree-tos -m velan@vkatos.com

# 5. Install real nginx config (with SSL)
echo "[5/5] Installing SSL nginx config..."
cp "$REPO_DIR/scripts/nginx/app.vkatos.com.conf" /etc/nginx/sites-enabled/app.vkatos.com
nginx -t && systemctl reload nginx

echo ""
echo "=== Setup complete ==="
echo "  app.vkatos.com → AetherOS (port 8000)"
