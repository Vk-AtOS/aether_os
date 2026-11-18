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
  --from-literal=SAML_SP_ENTITY_ID="" \
  --from-literal=SAML_SP_ACS_URL="" \
  -n aetheros
```

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

## 3. Run Alembic Migrations

After the `postgres` StatefulSet pod is ready, run migrations as a one-off Job:

```bash
kubectl run alembic-migrate \
  --image=aetheros/api:latest \
  --restart=Never \
  --namespace=aetheros \
  --env="DATABASE_URL=$(kubectl get secret aetheros-secrets -n aetheros -o jsonpath='{.data.DATABASE_URL}' | base64 -d)" \
  -- alembic upgrade head
```

Wait for it to complete and check logs:

```bash
kubectl logs alembic-migrate -n aetheros
kubectl delete pod alembic-migrate -n aetheros
```

Alternatively, create a Kubernetes Job manifest:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: alembic-migrate
  namespace: aetheros
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: alembic
          image: aetheros/api:latest
          command: ["alembic", "upgrade", "head"]
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: aetheros-secrets
                  key: DATABASE_URL
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
