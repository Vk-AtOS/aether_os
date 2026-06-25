#!/usr/bin/env bash
# vps-setup-subdomains.sh
# Run ONCE on the VPS to configure nginx + SSL for app.vkatos.com and dcsp.vkatos.com.
# Prerequisites: DNS A records for both subdomains must already point to this server.
set -euo pipefail

REPO_DIR="/home/aether_os"

echo "=== VPS Subdomain Setup ==="

# 1. Install certbot if not present
if ! command -v certbot &>/dev/null; then
  echo "[1/6] Installing certbot..."
  apt-get install -y certbot python3-certbot-nginx
else
  echo "[1/6] certbot already installed."
fi

# 2. Copy nginx configs
echo "[2/6] Installing nginx configs..."
cp "$REPO_DIR/scripts/nginx/app.vkatos.com.conf" /etc/nginx/sites-available/app.vkatos.com
cp "$REPO_DIR/scripts/nginx/dcsp.vkatos.com.conf" /etc/nginx/sites-available/dcsp.vkatos.com
ln -sf /etc/nginx/sites-available/app.vkatos.com  /etc/nginx/sites-enabled/app.vkatos.com
ln -sf /etc/nginx/sites-available/dcsp.vkatos.com /etc/nginx/sites-enabled/dcsp.vkatos.com

# 3. Temporarily allow HTTP-only so certbot can do its challenge
# (Replace ssl blocks with http-only stubs)
echo "[3/6] Creating temp HTTP configs for certbot challenge..."
cat > /etc/nginx/sites-available/app.vkatos.com.tmp <<'EOF'
server { listen 80; server_name app.vkatos.com; location / { proxy_pass http://127.0.0.1:8000; } }
EOF
cat > /etc/nginx/sites-available/dcsp.vkatos.com.tmp <<'EOF'
server { listen 80; server_name dcsp.vkatos.com; location / { proxy_pass http://127.0.0.1:8001; } }
EOF

cp /etc/nginx/sites-available/app.vkatos.com.tmp  /etc/nginx/sites-enabled/app.vkatos.com
cp /etc/nginx/sites-available/dcsp.vkatos.com.tmp /etc/nginx/sites-enabled/dcsp.vkatos.com
nginx -t && systemctl reload nginx

# 4. Obtain SSL certs
echo "[4/6] Obtaining SSL certificates..."
certbot certonly --nginx -d app.vkatos.com --non-interactive --agree-tos -m velan@vkatos.com
certbot certonly --nginx -d dcsp.vkatos.com --non-interactive --agree-tos -m velan@vkatos.com

# 5. Install real nginx configs (with SSL)
echo "[5/6] Installing SSL nginx configs..."
cp "$REPO_DIR/scripts/nginx/app.vkatos.com.conf"  /etc/nginx/sites-enabled/app.vkatos.com
cp "$REPO_DIR/scripts/nginx/dcsp.vkatos.com.conf" /etc/nginx/sites-enabled/dcsp.vkatos.com
nginx -t && systemctl reload nginx

# 6. Create /home/dcsp directory and set permissions
echo "[6/6] Preparing /home/dcsp..."
mkdir -p /home/dcsp
chmod 750 /home/dcsp

echo ""
echo "=== Setup complete ==="
echo "  app.vkatos.com  → AetherOS (port 8000)"
echo "  dcsp.vkatos.com → DCSP     (port 8001)"
echo ""
echo "Next steps:"
echo "  1. Copy DCSP source: bash $REPO_DIR/scripts/deploy-dcsp.sh"
echo "  2. Edit /home/dcsp/.env with real secrets"
echo "  3. Re-run deploy-dcsp.sh to start with real config"
