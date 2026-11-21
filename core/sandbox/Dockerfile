# Image that runs generated apps, their builds and tests (core/sandbox/docker_backend.py).
# Build on the Docker host:
#   docker build -f core/sandbox/Dockerfile -t aether-sandbox:1 core/sandbox
#
# Holds only toolchains: no platform code, no secrets. Containers from it run with a
# read-only root filesystem as a non-root uid (docker_backend.docker_args), so nothing
# below is writable at run time; each run's packages go into a venv in its run dir.
FROM node:20.20.1-bookworm-slim@sha256:17281e8d1dc4d671976c6b89a12f47a44c2f390b63a989e2e327631041f544fd AS node

FROM python:3.11.14-slim-bookworm@sha256:65a93d69fa75478d554f4ad27c85c1e69fa184956261b4301ebaf6dbb0a3543d
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && node --version && npm --version
# What every generated FastAPI backend imports, so a preview needs no download for these.
RUN pip install --no-cache-dir \
      "fastapi>=0.110" "uvicorn[standard]>=0.29" "sqlalchemy[asyncio]>=2" aiosqlite httpx alembic \
      pydantic pydantic-settings email-validator python-multipart \
      "pyjwt[crypto]" passlib bcrypt pytest pytest-asyncio
USER 10001:10001
