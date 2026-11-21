# ── Stage 1: Build the React/Vite dashboard ──────────────────────────────────
# Base images are pinned by tag AND digest so a rebuild is reproducible; bump both together (see docs/ops/RUNBOOKS.md, 'Images').
FROM node:20.20.1-slim@sha256:17281e8d1dc4d671976c6b89a12f47a44c2f390b63a989e2e327631041f544fd AS frontend-builder

WORKDIR /build

# Copy only the dashboard source so layer caching works when only Python changes
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --silent

COPY dashboard/ ./
RUN npm run build
# Output lands in /build/dist/

# ── Stage 2: Python API server ────────────────────────────────────────────────
FROM python:3.11.14-slim-bookworm@sha256:65a93d69fa75478d554f4ad27c85c1e69fa184956261b4301ebaf6dbb0a3543d

WORKDIR /srv

RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client curl git \
    && rm -rf /var/lib/apt/lists/*

# Use the pinned lockfile for reproducible builds (requirements.txt is unpinned)
# The sandbox backend shells out to `docker` (core/sandbox/docker_backend.py) through DOCKER_HOST=tcp://docker-proxy:2375, the filtered socket proxy (see docker-compose.yml); the API has no socket.
COPY --from=docker:27.5.1-cli@sha256:851f91d241214e7c6db86513b270d58776379aacc5eb9c4a87e5b47115e3065c /usr/local/bin/docker /usr/local/bin/docker

COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

# Copy source into a directory named `aether_os` so `import aether_os` resolves
COPY . ./aether_os/

# Copy the pre-built dashboard into the expected location.
# api.py mounts: <repo_root>/dashboard/dist  →  /srv/aether_os/dashboard/dist
COPY --from=frontend-builder /build/dist ./aether_os/dashboard/dist/

ENV PYTHONPATH=/srv PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

RUN pip install -e ./aether_os/

# Guardian file-integrity baseline belongs to this build, not to the first boot of the (persistent) Redis volume: hash
# the critical files now, into a root-owned read-only manifest the app user cannot rewrite. AETHER_BUILD_ID (e.g. the git
# commit) is optional; it lives in the image config, so a restart from inside the container cannot change it. Declared
# here, after the heavy layers, so changing it only re-runs this step. See docs/codebase_map/sections/10_core_platform_governance.md §3.8.
ARG AETHER_BUILD_ID=""
ENV AETHER_BUILD_ID=${AETHER_BUILD_ID}
RUN python -c "from aether_os.core.guardian.build_identity import write_manifest; write_manifest()" \
    && chmod 0444 ./aether_os/.guardian_build_manifest.json

# --home: a system user otherwise gets HOME=/nonexistent, and the code keeps its state under ~/.aether_os (compose mounts
# /home/aether/.aether_os); the API and preview crashed at import with PermissionError: '/nonexistent'.
RUN addgroup --system aether && adduser --system --ingroup aether --home /home/aether aether
USER aether

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8000/healthz || exit 1

# SIGTERM reaches uvicorn (exec form, PID 1): it stops accepting and finishes in-flight requests.
CMD ["uvicorn", "aether_os.gateway.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
