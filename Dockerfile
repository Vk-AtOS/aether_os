# ── Stage 1: Build the React/Vite dashboard ──────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /build

# Copy only the dashboard source so layer caching works when only Python changes
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --silent

COPY dashboard/ ./
RUN npm run build
# Output lands in /build/dist/

# ── Stage 2: Python API server ────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /srv

RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client curl git \
    && rm -rf /var/lib/apt/lists/*

# Use the pinned lockfile for reproducible builds (requirements.txt is unpinned)
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

# Copy source into a directory named `aether_os` so `import aether_os` resolves
COPY . ./aether_os/

# Copy the pre-built dashboard into the expected location.
# api.py mounts: <repo_root>/dashboard/dist  →  /srv/aether_os/dashboard/dist
COPY --from=frontend-builder /build/dist ./aether_os/dashboard/dist/

ENV PYTHONPATH=/srv

RUN pip install -e ./aether_os/

RUN addgroup --system aether && adduser --system --ingroup aether aether
USER aether

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "aether_os.gateway.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
