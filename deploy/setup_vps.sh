#!/usr/bin/env bash
# =============================================================================
# AetherOS — VPS Setup Script
# Tested on: Ubuntu 22.04 LTS
#
# Usage:
#   export DOMAIN=aetheros.yourdomain.com
#   export EMAIL=you@example.com          # for certbot
#   sudo bash setup_vps.sh
#
# What this does:
#   1. System updates + Python 3.11, Node 20, nginx, certbot
#   2. Creates /opt/aetheros from current repo
#   3. Python venv + pip install
#   4. Node + npm build of dashboard
#   5. systemd service install + enable
#   6. nginx config + TLS via certbot
# =============================================================================
set -euo pipefail
DOMAIN="${DOMAIN:?Set DOMAIN env var before running}"
EMAIL="${EMAIL:?Set EMAIL env var before running}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"   # parent of deploy/
INSTALL_DIR=/opt/aetheros
SERVICE_USER=aetheros

echo "=== AetherOS VPS Setup ==="
echo "Domain : $DOMAIN"
echo "Repo   : $REPO_DIR"
echo "Install: $INSTALL_DIR"
echo ""

# ── 1. System packages ────────────────────────────────────────────────────────
apt-get update -y
apt-get install -y \
    python3.11 python3.11-venv python3.11-dev \
    build-essential curl git \
    nginx certbot python3-certbot-nginx \
    pgbouncer postgresql-client \
    ufw

# ── 2. Node 20 (via NodeSource) ───────────────────────────────────────────────
if ! command -v node &>/dev/null || [[ "$(node --version | cut -d. -f1)" != "v20" ]]; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
fi

# ── 3. Ollama ─────────────────────────────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
fi

# B10: bind Ollama to localhost only — prevent free public access and security risk
mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/override.conf <<'OVERRIDE'
[Service]
Environment=OLLAMA_HOST=127.0.0.1
OVERRIDE
systemctl daemon-reload
systemctl enable --now ollama

# ── 4. Create system user ─────────────────────────────────────────────────────
id -u "$SERVICE_USER" &>/dev/null || useradd --system --home "$INSTALL_DIR" --shell /bin/false "$SERVICE_USER"

# ── 5. Copy repo → install dir ────────────────────────────────────────────────
mkdir -p "$INSTALL_DIR"
rsync -a --exclude='.git' --exclude='node_modules' --exclude='__pycache__' \
    --exclude='*.pyc' --exclude='.env' \
    "$REPO_DIR/" "$INSTALL_DIR/"

# ── 6. Python venv ────────────────────────────────────────────────────────────
python3.11 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip wheel
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# ── 7. Dashboard build ────────────────────────────────────────────────────────
(cd "$INSTALL_DIR/dashboard" && npm ci && npm run build)

# ── 8. .env — prompt if missing ───────────────────────────────────────────────
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
    echo ""
    echo "⚠️  No .env found. Creating from template — fill in your keys!"
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env" 2>/dev/null || \
    cat > "$INSTALL_DIR/.env" <<ENV
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=REPLACE_WITH_YOUR_GEMINI_KEY
PRIMARY_LLM=ollama
OLLAMA_MODEL=qwen2.5-coder:3b
AETHER_ADMIN_EMAIL=admin@example.com
AETHER_ADMIN_PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(16))")
AETHER_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
AETHER_ONE_ZT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
CORS_ORIGINS=https://$DOMAIN
DATABASE_URL=sqlite+aiosqlite:///aether_os.db
ENV
    echo "→ Edit $INSTALL_DIR/.env before starting the service!"
fi

# ── 9. Permissions ────────────────────────────────────────────────────────────
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
chmod 640 "$INSTALL_DIR/.env"

# ── 10. Log dir ───────────────────────────────────────────────────────────────
mkdir -p /var/log/aetheros
chown "$SERVICE_USER:$SERVICE_USER" /var/log/aetheros

# ── 10a. Log rotation ─────────────────────────────────────────────────────────
if [[ -f "$REPO_DIR/deploy/logrotate.d/aetheros" ]]; then
    cp "$REPO_DIR/deploy/logrotate.d/aetheros" /etc/logrotate.d/aetheros
    chmod 644 /etc/logrotate.d/aetheros
    echo "→ Log rotation configured at /etc/logrotate.d/aetheros"
fi

# ── 11a. PgBouncer — connection pooler (C6) ───────────────────────────────────
if [[ -f "$REPO_DIR/deploy/pgbouncer.ini" ]]; then
    cp "$REPO_DIR/deploy/pgbouncer.ini" /etc/pgbouncer/pgbouncer.ini
    # Only copy userlist template if not already populated with real hashes
    if [[ ! -f /etc/pgbouncer/userlist.txt ]] || grep -q "REPLACE_WITH_REAL_HASH" /etc/pgbouncer/userlist.txt 2>/dev/null; then
        cp "$REPO_DIR/deploy/pgbouncer_userlist.txt" /etc/pgbouncer/userlist.txt
        echo "⚠️  /etc/pgbouncer/userlist.txt contains placeholder hashes — update before starting PgBouncer!"
    fi
    chown postgres:postgres /etc/pgbouncer/pgbouncer.ini /etc/pgbouncer/userlist.txt
    chmod 640 /etc/pgbouncer/pgbouncer.ini /etc/pgbouncer/userlist.txt
    systemctl enable --now pgbouncer || echo "PgBouncer enable failed — check /etc/pgbouncer/userlist.txt"
    echo "→ PgBouncer listening on 127.0.0.1:6432"
    echo "→ Update DATABASE_URL in .env to: postgresql+asyncpg://aetheros:<pw>@127.0.0.1:6432/aetheros"
fi

# ── 11. systemd service ───────────────────────────────────────────────────────
cp "$REPO_DIR/deploy/aetheros.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable aetheros

# ── 12. nginx ─────────────────────────────────────────────────────────────────
NGINX_CONF=/etc/nginx/sites-available/aetheros
sed "s/APP_DOMAIN_PLACEHOLDER/$DOMAIN/g" "$REPO_DIR/deploy/nginx.conf" > "$NGINX_CONF"
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/aetheros
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

# ── 13. TLS via certbot ───────────────────────────────────────────────────────
certbot --nginx -d "$DOMAIN" --email "$EMAIL" --agree-tos --non-interactive --redirect

# ── 14. Firewall ──────────────────────────────────────────────────────────────
ufw allow 'Nginx Full'
ufw allow OpenSSH
# B10: block Ollama from public internet — localhost only
ufw deny 11434
ufw --force enable

# ── 15. Start service ─────────────────────────────────────────────────────────
systemctl start aetheros
sleep 3
systemctl is-active aetheros && echo "✅ AetherOS is running!" || {
    echo "❌ Service failed to start — check logs:"
    journalctl -u aetheros -n 30 --no-pager
    exit 1
}

echo ""
echo "=== Setup complete ==="
echo "Dashboard : https://$DOMAIN"
echo "API docs  : https://$DOMAIN/api/docs"
echo "Logs      : journalctl -u aetheros -f"
echo "Admin pw  : $(grep AETHER_ADMIN_PASS $INSTALL_DIR/.env | cut -d= -f2)"
