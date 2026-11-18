#!/usr/bin/env bash
# Applies the manifests in dependency order, but ONLY after the placeholder check passes.
# Usage: deploy/kubernetes/apply.sh [DIR]   (DIR = your filled-in copy; default: this directory)
set -euo pipefail
D="${1:-$(cd "$(dirname "$0")" && pwd)}"
python3 "$(dirname "$0")/../../scripts/ci/check_placeholders.py" "$D"
for f in namespace secret configmap postgres redis; do kubectl apply -f "$D/$f.yaml"; done
kubectl wait --for=condition=ready pod -l app=postgres -n aetheros --timeout=120s
kubectl wait --for=condition=ready pod -l app=redis -n aetheros --timeout=60s
kubectl apply -f "$D/api.yaml" -f "$D/ingress.yaml"
