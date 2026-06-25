#!/usr/bin/env bash
# vps-setup-and-deploy-dcsp.sh
# Run on VPS after git pull. Sets up nginx for both subdomains (HTTP only,
# Cloudflare proxy handles SSL) and deploys DCSP alongside AetherOS.
set -euo pipefail

REPO_DIR="/home/aether_os"
DCSP_DIR="/home/dcsp"

echo "=== VPS Nginx + DCSP Setup ==="

# 1. Write nginx config for app.vkatos.com (HTTP-only; Cloudflare proxies HTTPS)
echo "[1/6] Writing nginx config: app.vkatos.com..."
cat > /etc/nginx/sites-available/app.vkatos.com <<'CONF'
server {
    listen 80;
    server_name app.vkatos.com;
    client_max_body_size 50M;

    location /api/runs/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto https;
        proxy_buffering    off;
        proxy_cache        off;
        proxy_read_timeout 600s;
    }

    location /ws/ {
        proxy_pass          http://127.0.0.1:8000;
        proxy_http_version  1.1;
        proxy_set_header    Upgrade $http_upgrade;
        proxy_set_header    Connection "upgrade";
        proxy_set_header    Host $host;
        proxy_read_timeout  3600s;
    }

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto https;
        proxy_read_timeout 600s;
    }
}
CONF

# 2. Write nginx config for dcsp.vkatos.com
echo "[2/6] Writing nginx config: dcsp.vkatos.com..."
cat > /etc/nginx/sites-available/dcsp.vkatos.com <<'CONF'
server {
    listen 80;
    server_name dcsp.vkatos.com;
    client_max_body_size 20M;

    location /ws {
        proxy_pass          http://127.0.0.1:8001;
        proxy_http_version  1.1;
        proxy_set_header    Upgrade $http_upgrade;
        proxy_set_header    Connection "upgrade";
        proxy_set_header    Host $host;
        proxy_read_timeout  3600s;
    }

    location / {
        proxy_pass         http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto https;
        proxy_read_timeout 120s;
    }
}
CONF

# 3. Enable both sites
echo "[3/6] Enabling nginx sites..."
ln -sf /etc/nginx/sites-available/app.vkatos.com  /etc/nginx/sites-enabled/app.vkatos.com
ln -sf /etc/nginx/sites-available/dcsp.vkatos.com /etc/nginx/sites-enabled/dcsp.vkatos.com

# 4. Test and reload nginx
echo "[4/6] Testing and reloading nginx..."
nginx -t && systemctl reload nginx
echo "  nginx: OK"

# 5. Create /home/dcsp and set permissions
echo "[5/6] Preparing /home/dcsp..."
mkdir -p "$DCSP_DIR"
chmod 750 "$DCSP_DIR"

# 6. Deploy DCSP (rsync + docker compose up)
echo "[6/6] Deploying DCSP..."
bash "$REPO_DIR/scripts/deploy-dcsp.sh"

echo ""
echo "=== Setup complete ==="
echo "  app.vkatos.com  → AetherOS (port 8000)"
echo "  dcsp.vkatos.com → DCSP     (port 8001)"
