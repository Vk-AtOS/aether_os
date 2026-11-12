#!/usr/bin/env bash
# Host firewall for the Docker sandbox networks (core/sandbox/docker_backend.py).
# Run as root on the Docker host after every boot (or persist with iptables-persistent).
# Idempotent. Creates the two sandbox networks if the gateway has not yet.
#
#   br-aether-run  (aether-sbx-run)    the running generated app: NO new connections
#                                      anywhere — not the host, not the LAN, not the
#                                      internet. Only replies to the published port.
#   br-aether-egr  (aether-sbx-egress) dependency installs: public internet only —
#                                      no host, no private ranges, no cloud metadata.
set -euo pipefail

RUN_IF=br-aether-run
EGR_IF=br-aether-egr
BLOCKED="127.0.0.0/8 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 169.254.0.0/16 224.0.0.0/4"

net() {  # name bridge masquerade
  docker network inspect "$1" >/dev/null 2>&1 || docker network create --driver bridge \
    -o com.docker.network.bridge.name="$2" \
    -o com.docker.network.bridge.enable_icc=false \
    -o com.docker.network.bridge.enable_ip_masquerade="$3" "$1"
}
net aether-sbx-run "$RUN_IF" false
net aether-sbx-egress "$EGR_IF" true

rule() {  # chain, then the rule; inserted at the top once
  local chain="$1"; shift
  iptables -C "$chain" "$@" 2>/dev/null || iptables -I "$chain" 1 "$@"
}

# Rules are inserted at position 1, so the ACCEPT/RETURN for replies goes in last (ends up first).
for IF in "$RUN_IF" "$EGR_IF"; do
  # Container -> this host (Postgres, Redis, the gateway, sshd, the Docker API...): nothing new.
  rule INPUT -i "$IF" -j DROP
  rule INPUT -i "$IF" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
done

# App network: no new forwarded connections at all.
rule DOCKER-USER -i "$RUN_IF" -j DROP
rule DOCKER-USER -i "$RUN_IF" -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN

# Install network: internet yes, private / link-local (169.254.169.254 metadata) no.
for CIDR in $BLOCKED; do
  rule DOCKER-USER -i "$EGR_IF" -d "$CIDR" -j DROP
done

# The sandbox networks are IPv4-only (Docker's default); refuse IPv6 from them regardless.
if command -v ip6tables >/dev/null; then
  for IF in "$RUN_IF" "$EGR_IF"; do
    ip6tables -C INPUT -i "$IF" -j DROP 2>/dev/null || ip6tables -I INPUT 1 -i "$IF" -j DROP
    ip6tables -C FORWARD -i "$IF" -j DROP 2>/dev/null || ip6tables -I FORWARD 1 -i "$IF" -j DROP
  done
fi
echo "sandbox firewall rules in place for $RUN_IF and $EGR_IF"
