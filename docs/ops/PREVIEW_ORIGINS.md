# Preview origins: wildcard DNS and certificate (KAN-75)

Generated apps are served from `https://<run-id>.<PREVIEW_DOMAIN>`, never from the dashboard origin. The platform already
refuses to serve previews otherwise (`core/run_app/preview_token.py: config_problem()`, enforced at start by
`gateway/preview_server.py`: unset origin, short secret, origin equal to the dashboard origin, or listed in `CORS_ORIGINS`).
This page covers what production adds: wildcard DNS, a wildcard certificate and automatic renewal.

## 1. DNS (one wildcard record)

| Name | Type | Value |
|---|---|---|
| `preview.example.com` | A / ALIAS | the preview load balancer (or the nginx host) |
| `*.preview.example.com` | A / ALIAS | the same target |

Terraform (AWS): `deploy/terraform/aws/modules/edge` creates both records in Route 53. Use a **separate registrable domain** for
the strongest isolation (cookies set by the dashboard can never be read by a preview); a sub-domain of the dashboard's domain is
acceptable only because previews are also `__Host-`-scoped and token audience-bound.

## 2. Certificate, three ways (pick one)

* **VPS with nginx**: `PREVIEW_DOMAIN=... CERTBOT_DNS_PLUGIN=route53 CERTBOT_EMAIL=... bash deploy/preview/issue-wildcard-cert.sh`.
  Wildcards need DNS-01. The script installs a deploy hook (`nginx -t && systemctl reload nginx`); renewal runs from
  `certbot.timer` or `deploy/preview/aetheros-cert-renew.timer`.
* **Kubernetes**: `deploy/kubernetes/preview-certificate.yaml` (cert-manager `Certificate`, renews 30 days before expiry).
* **AWS managed**: ACM certificate for `preview.example.com` and `*.preview.example.com`, DNS validated in Route 53 by Terraform;
  ACM renews it itself. Attach it to the preview load balancer listener.

DNS credentials: use an instance role / workload identity restricted to the one hosted zone. No credential goes in the repository.

## 3. Startup behaviour

Set `AETHER_PREVIEW_ORIGIN=https://preview.example.com`, `AETHER_PREVIEW_SECRET` (32+ characters), and keep that origin out of
`CORS_ORIGINS`. The preview server exits with "preview server refuses to start" if any rule above is broken.

## 4. Staging test (needs the real record and certificate)

    python3.11 scripts/check_preview_origin.py https://preview.example.com --min-days 14

It resolves two random labels, checks they point to the same address as the base host, opens TLS with a random label as SNI
(a certificate without the wildcard fails), and checks at least 14 days remain. Exit 0 = pass. Add it to the deploy smoke test
once a staging domain exists. Unit tests for the matching logic run without network (`tests/test_preview_wildcard.py`).

UNVERIFIED: no real wildcard record or certificate was available when this was written; the script has only run against
synthetic certificates.
