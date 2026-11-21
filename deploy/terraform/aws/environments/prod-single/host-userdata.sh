#!/bin/bash
# First boot of the Docker host (Amazon Linux 2023): Docker, the compose and buildx plugins, git, PostgreSQL client.
set -euo pipefail
dnf install -y docker git postgresql15 jq
mkdir -p /usr/local/lib/docker/cli-plugins
arch=$(uname -m)
curl -fsSL -o /usr/local/lib/docker/cli-plugins/docker-compose \
  "https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-${arch}"
curl -fsSL -o /usr/local/lib/docker/cli-plugins/docker-buildx \
  "https://github.com/docker/buildx/releases/download/v0.17.1/buildx-v0.17.1.linux-amd64"
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose /usr/local/lib/docker/cli-plugins/docker-buildx
systemctl enable --now docker
usermod -aG docker ssm-user 2>/dev/null || true
touch /var/run/aetheros-host-ready
