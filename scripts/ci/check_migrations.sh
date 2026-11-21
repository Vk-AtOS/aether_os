#!/usr/bin/env bash
# Migration check against a SCRATCH PostgreSQL (never a server): the exact steps compose, deploy.sh and Helm run.
#   DATABASE_URL=postgresql://user:pw@localhost:5432/scratch bash scripts/ci/check_migrations.sh
# 1. the Alembic chain has one head (two heads make `upgrade head` fail on a real database);
# 2. an EMPTY database is built by scripts/db_migrate.py (create + stamp head);
# 3. a second run takes the EXISTING-database path (`alembic upgrade head` + schema_ddl) and must change nothing;
# 4. the audit-ledger triggers exist (the API refuses to start without them).
# Not covered: an upgrade from the previous release's real data (needs that release's database).
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${DATABASE_URL:?DATABASE_URL must point at a scratch PostgreSQL database}"
export AETHER_FIELD_KEY="${AETHER_FIELD_KEY:-$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')}"
# the package must be importable as aether_os: the checkout directory is that package
PKG="$(mktemp -d)"; ln -sfn "$PWD" "$PKG/aether_os"; export PYTHONPATH="$PKG${PYTHONPATH:+:$PYTHONPATH}"

heads=$(python -m alembic heads | grep -c '(head)' || true)
[ "$heads" = "1" ] || { echo "FAIL: alembic has $heads heads, expected 1"; python -m alembic heads; exit 1; }

first=$(python scripts/db_migrate.py | tail -1)
[ "$first" = "created" ] || { echo "FAIL: empty database -> '$first', expected 'created'"; exit 1; }
second=$(python scripts/db_migrate.py | tail -1)
[ "$second" = "upgraded" ] || { echo "FAIL: second run -> '$second', expected 'upgraded'"; exit 1; }

python - <<'PY'
import asyncio
from aether_os.core.db import get_engine, require_ledger_triggers
asyncio.run(require_ledger_triggers(get_engine()))
print("ledger triggers present")
PY
echo "migrations OK"
