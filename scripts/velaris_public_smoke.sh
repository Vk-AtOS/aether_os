#!/usr/bin/env bash
# Smoke test for the Velaris public host (KAN-128): bash scripts/velaris_public_smoke.sh https://public.example.com
# Allowed prefixes must reach the app (anything but the proxy's own 404); every other path must be 404.
set -u
BASE="${1:?usage: velaris_public_smoke.sh <base-url>}"
fail=0
code() { curl -s -o /dev/null -m 10 -w '%{http_code}' "$@"; }
for p in /careers/x /schedule/x /interview/x /sign/x; do
  c=$(code "$BASE$p"); body=$(curl -s -m 10 "$BASE$p" | head -c 200)
  # the proxy's own refusal is an empty-ish nginx 404; the app answers its own JSON/HTML (even 404 for an unknown token)
  if [[ "$c" == "000" || "$c" == "502" || "$c" == "503" ]]; then echo "FAIL $p -> $c (app not reachable)"; fail=1; else echo "ok   $p -> $c"; fi
  [[ "$body" == *"nginx"* ]] && { echo "FAIL $p answered by nginx"; fail=1; }
done
for p in /agents /flows /flows/pending /chat/channels /mail/mailboxes /control/tasks /hr/ATS_CORE/pipeline /metrics /docs /openapi.json /; do
  c=$(code "$BASE$p"); [[ "$c" == "404" ]] && echo "ok   $p -> 404" || { echo "FAIL $p -> $c (must be 404)"; fail=1; }
done
c=$(code -H 'Cookie: a=b' -H 'Authorization: Bearer x' -H 'X-Forwarded-For: 6.6.6.6' "$BASE/careers/x"); echo "info forged headers -> $c (check the app log shows the real client IP, not 6.6.6.6)"
exit $fail
