#!/usr/bin/env bash
# Installs a pinned gitleaks (Linux x64) into $1 (default ./.bin), verifying the published checksum.
set -euo pipefail
V=8.30.1; DEST="${1:-.bin}"; mkdir -p "$DEST"; T=$(mktemp -d)
B="https://github.com/gitleaks/gitleaks/releases/download/v$V"
curl -fsSL -o "$T/g.tgz" "$B/gitleaks_${V}_linux_x64.tar.gz"
curl -fsSL -o "$T/sums" "$B/gitleaks_${V}_checksums.txt"
(cd "$T" && grep " gitleaks_${V}_linux_x64.tar.gz\$" sums | sha256sum -c -)
tar -xzf "$T/g.tgz" -C "$DEST" gitleaks
