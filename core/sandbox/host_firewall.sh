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

# ...except DNS to this host's own upstream resolver(s). Docker's embedded DNS forwards a container's queries from the
# container's network, and on cloud hosts the resolver sits in a private range (AWS VPC resolver 172.31.0.2 or
# 169.254.169.253): the drops above blocked every lookup, so npm/pip installs hung until their timeout (AWS testbed
# run 8, 22 Nov 2026). Only port 53 to the configured resolver addresses is opened, nothing else in those ranges.
RESOLV=/etc/resolv.conf
grep -qE '^nameserver 127\.' "$RESOLV" 2>/dev/null && [ -f /run/systemd/resolve/resolv.conf ] && RESOLV=/run/systemd/resolve/resolv.conf
for NS in $(awk '$1=="nameserver" && $2 ~ /^[0-9.]+$/ && $2 !~ /^127\./ {print $2}' "$RESOLV" 2>/dev/null); do
  for PROTO in udp tcp; do
    rule DOCKER-USER -i "$EGR_IF" -d "$NS" -p "$PROTO" --dport 53 -j RETURN
  done
  echo "install network: DNS allowed to resolver $NS"
done

# Published app ports. With the gateway in a container (docker compose on Linux) the ports are
# published on the docker0 bridge address instead of 127.0.0.1 (core/sandbox/endpoints.py), so the
# API container can reach them. Pass the same AETHER_SANDBOX_PUBLISH_IP to this script: packets for
# that address are accepted only from this host's own interfaces (loopback, docker0, the compose
# bridges), never from the outside network.
# The address is checked by the SAME validator the gateway uses (publish_addr.py: loopback or RFC 1918
# only; no wildcard in any spelling, no link-local, no public, no hostname), and it prints the canonical form.
RAW_PUB_IP="${AETHER_SANDBOX_PUBLISH_IP:-}"
RAW_PUB_IP="${RAW_PUB_IP:-127.0.0.1}"
PUB_IP="$(python3 "$(dirname "$0")/publish_addr.py" "$RAW_PUB_IP")" || {
  echo "refusing AETHER_SANDBOX_PUBLISH_IP=$RAW_PUB_IP (see core/sandbox/publish_addr.py)" >&2
  exit 1
}
case "$PUB_IP" in
  127.*|::1) ;;  # loopback: unreachable from outside by construction
  *)
    # RFC 1918 also covers this host's own LAN/VPC address, which IS reachable from outside:
    # require the address to belong to docker0 or a Docker bridge.
    OWNER="$(ip -4 -o addr show | awk -v ip="$PUB_IP" '{split($4, a, "/"); if (a[1] == ip) print $2}')"
    case "$OWNER" in
      docker0|br-*) ;;
      *)
        echo "refusing AETHER_SANDBOX_PUBLISH_IP=$PUB_IP: not an address of docker0 or a Docker bridge (owner: ${OWNER:-none})" >&2
        exit 1 ;;
    esac
    iptables -t raw -N AETHER-SBX-PUB 2>/dev/null || true
    iptables -t raw -F AETHER-SBX-PUB
    iptables -t raw -A AETHER-SBX-PUB -i lo -j RETURN
    iptables -t raw -A AETHER-SBX-PUB -i docker0 -j RETURN
    iptables -t raw -A AETHER-SBX-PUB -i br+ -j RETURN
    iptables -t raw -A AETHER-SBX-PUB -j DROP
    iptables -t raw -C PREROUTING -d "$PUB_IP" -j AETHER-SBX-PUB 2>/dev/null \
      || iptables -t raw -I PREROUTING 1 -d "$PUB_IP" -j AETHER-SBX-PUB
    echo "published sandbox ports on $PUB_IP accepted only from local interfaces"
    ;;
esac

# The sandbox networks are IPv4-only (Docker's default); refuse IPv6 from them regardless.
if command -v ip6tables >/dev/null; then
  for IF in "$RUN_IF" "$EGR_IF"; do
    ip6tables -C INPUT -i "$IF" -j DROP 2>/dev/null || ip6tables -I INPUT 1 -i "$IF" -j DROP
    ip6tables -C FORWARD -i "$IF" -j DROP 2>/dev/null || ip6tables -I FORWARD 1 -i "$IF" -j DROP
  done
fi
echo "sandbox firewall rules in place for $RUN_IF and $EGR_IF"
