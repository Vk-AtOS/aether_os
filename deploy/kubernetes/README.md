# AetherOS Kubernetes Deployment

## Prerequisites

- `kubectl` configured against your cluster
- `cert-manager` installed (for TLS): https://cert-manager.io/docs/installation/
- `ingress-nginx` controller installed: https://kubernetes.github.io/ingress-nginx/deploy/
- A container registry with `aetheros/api:latest` pushed

## 1. Set Secrets

Edit `secret.yaml` and replace every `REPLACE_ME_*` placeholder with real values,
**or** create the secret directly from a local `.env` file:

```bash
kubectl create namespace aetheros
kubectl create secret generic aetheros-secrets \
  --from-literal=AETHER_SECRET_KEY="$(openssl rand -hex 32)" \
  --from-literal=ANTHROPIC_API_KEY="sk-ant-..." \
  --from-literal=OPENROUTER_API_KEY="or-..." \
  --from-literal=AETHER_ONE_ZT_SECRET="$(openssl rand -hex 32)" \
  --from-literal=POSTGRES_PASSWORD="$(openssl rand -hex 20)" \
  --from-literal=REDIS_PASSWORD="$(openssl rand -hex 20)" \
  --from-literal=DATABASE_URL="postgresql://aether_user:<POSTGRES_PASSWORD>@postgres:5432/aether_os" \
  --from-literal=REDIS_URL="redis://:<REDIS_PASSWORD>@redis:6379/0" \
  --from-literal=AETHER_FIELD_KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
  --from-literal=AETHER_PREVIEW_SECRET="$(openssl rand -hex 32)" \
  --from-literal=AETHER_LEDGER_SIGNING_KEY_PEM="$(openssl genpkey -algorithm ED25519)" \
  --from-literal=VELARIS_API_SECRET="" \
  --from-literal=VELARIS_IDENTITY_PRIVATE_KEY_PEM="" \
  --from-literal=SAML_SP_ENTITY_ID="" \
  --from-literal=SAML_SP_ACS_URL="" \
  --from-literal=AETHER_JWT_PRIVATE_KEY_B64="" \
  --from-literal=AETHER_JWT_PUBLIC_KEY_B64="" \
  -n aetheros
```

`api.yaml` reads every key above through `secretKeyRef`; a key missing from the Secret is a pod config error. The ledger
signing key is mounted as a 0600 file shared by all replicas (back it up apart from the cluster).

Update `CORS_ORIGINS` and `FRONTEND_URL` in `configmap.yaml` and `yourdomain.com`
in `ingress.yaml` to match your actual domain.

## 2. Apply Manifests (in order)

```bash
# Prefer: deploy/kubernetes/apply.sh <your-filled-copy>  (refuses unmodified templates)
kubectl apply -f deploy/kubernetes/namespace.yaml
kubectl apply -f deploy/kubernetes/secret.yaml
kubectl apply -f deploy/kubernetes/configmap.yaml
kubectl apply -f deploy/kubernetes/postgres.yaml
kubectl apply -f deploy/kubernetes/redis.yaml
# Wait for postgres and redis to be ready:
kubectl wait --for=condition=ready pod -l app=postgres -n aetheros --timeout=120s
kubectl wait --for=condition=ready pod -l app=redis -n aetheros --timeout=60s
kubectl apply -f deploy/kubernetes/api.yaml
kubectl apply -f deploy/kubernetes/ingress.yaml
```

Or apply everything at once (Kubernetes handles dependency ordering via readiness probes):

```bash
kubectl apply -f deploy/kubernetes/
```

## 3. Database schema

`migrate-job.yaml` runs `python scripts/db_migrate.py`, the same command compose and `deploy/deploy.sh` run: an empty
database is created from the models and stamped at head; an existing one gets `alembic upgrade head`; both then apply the
audit-ledger triggers. (`alembic upgrade head` alone cannot build an empty database.) The API pods exit while the schema is
not at head and restart until the job finishes, so applying the whole directory is safe.

```bash
kubectl -n aetheros wait --for=condition=complete job/aetheros-migrate --timeout=300s
kubectl -n aetheros logs job/aetheros-migrate
kubectl -n aetheros delete job aetheros-migrate     # before the next upgrade (Job specs are immutable)
```

## 4. Verify

```bash
kubectl get pods -n aetheros
kubectl get ingress -n aetheros
kubectl logs -l app=aetheros-api -n aetheros --tail=50
```

## 5. Scaling

HPA is configured for min 2 / max 10 replicas at 70% CPU utilization.
To manually scale:

```bash
kubectl scale deployment aetheros-api --replicas=4 -n aetheros
```
