# Image that runs generated apps, their builds and tests (core/sandbox/docker_backend.py).
# Build on the Docker host:
#   docker build -f core/sandbox/Dockerfile -t aether-sandbox:1 core/sandbox
#
# Holds only toolchains: no platform code, no secrets. Containers from it run with a
# read-only root filesystem as a non-root uid (docker_backend.docker_args), so nothing
# below is writable at run time; each run's packages go into a venv in its run dir.
FROM node:20-bookworm-slim AS node

FROM python:3.11-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && node --version && npm --version
# What every generated FastAPI backend imports, so a preview needs no download for these.
RUN pip install --no-cache-dir \
      "fastapi>=0.110" "uvicorn[standard]>=0.29" "sqlalchemy>=2" aiosqlite httpx alembic \
      pydantic pydantic-settings email-validator python-multipart \
      "python-jose[cryptography]" passlib bcrypt pyjwt pytest pytest-asyncio
USER 10001:10001
