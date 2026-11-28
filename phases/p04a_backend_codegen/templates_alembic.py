"""Alembic setup for the generated backend (KAN-267): alembic.ini, an async-aware env.py and an INITIAL migration.

A generated backend used to ship an empty ``alembic/versions`` and build its schema with ``create_all`` on every
start, so a production database could never be created (or later changed) by a migration. The initial migration is
now produced by running alembic's own autogenerate, in the sandbox, against an empty throw-away SQLite file: it is
rendered from the generated models' metadata (never from the database), so the result is the same for SQLite and
PostgreSQL and always matches the models that were just written.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from aether_os.core.sandbox import phase_exec

logger = logging.getLogger(__name__)

_ALEMBIC_INI = """\
[alembic]
script_location = alembic
prepend_sys_path = .
[loggers]
keys = root,sqlalchemy,alembic
[handlers]
keys = console
[formatters]
keys = generic
[logger_root]
level = WARN
handlers = console
qualname =
[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine
[logger_alembic]
level = INFO
handlers =
qualname = alembic
[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic
[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
"""

_ALEMBIC_ENV_PY = """\
# Alembic environment: async engine, DATABASE_URL from the environment, every model registered on Base.
import asyncio
import importlib
import re
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

# The app imports its modules as `database` / `models` with src/ on sys.path. Importing them as `src.database`
# made a second module (and a second, empty Base), so autogenerate saw no tables.
_SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(_SRC))

try:  # `make migrate` runs alembic outside the app, so read .env the way main.py does (real env vars win)
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_SRC.parent / ".env", override=False)
except ImportError:
    pass

# database.py reads DATABASE_URL (and refuses to start without it) and normalises it to an async driver.
from database import DATABASE_URL, Base  # noqa: E402

# Register every table the app declares (models.py plus the optional pattern modules) without importing main:
# main pulls in auth, which creates the JWT signing key on import.
_DECL = re.compile(r"^class \\w+\\((?:Base|_Base)\\)", re.M)
for _path in sorted(_SRC.rglob("*.py")):
    if _DECL.search(_path.read_text(encoding="utf-8", errors="ignore")):
        importlib.import_module(".".join(_path.relative_to(_SRC).with_suffix("").parts))

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=DATABASE_URL, target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
"""

_ALEMBIC_SCRIPT_PY_MAKO = """\
\"\"\"${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
\"\"\"
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
"""


def write_alembic_scaffold(output_dir: Path) -> None:
    """Write alembic.ini, env.py, script.py.mako and versions/ into *output_dir*."""
    alembic_dir = output_dir / "alembic"
    (alembic_dir / "versions").mkdir(parents=True, exist_ok=True)
    (output_dir / "alembic.ini").write_text(_ALEMBIC_INI)
    (alembic_dir / "env.py").write_text(_ALEMBIC_ENV_PY)
    (alembic_dir / "script.py.mako").write_text(_ALEMBIC_SCRIPT_PY_MAKO)
    (alembic_dir / "README").write_text(
        "Apply migrations:    alembic upgrade head   (the container entrypoint does this on every start)\n"
        "Generate a migration: alembic revision --autogenerate -m 'description'\n"
        "Rollback one step:   alembic downgrade -1\n"
    )


class MigrationError(RuntimeError):
    """The initial migration could not be generated; the backend would not be deployable."""


async def generate_initial_migration(output_dir: Path) -> Path:
    """Run alembic autogenerate against an empty SQLite file and return the written revision file.

    Needs the generated app's dependencies in the sandbox interpreter (the smoke test needs them too).
    """
    versions = output_dir / "alembic" / "versions"
    for old in versions.glob("*.py"):
        old.unlink()
    tmp_db = output_dir / "_autogen.db"
    tmp_key = output_dir / "_autogen_key.pem"
    env = {"DATABASE_URL": f"sqlite+aiosqlite:///{tmp_db}", "ENVIRONMENT": "development",
           "SECRET_KEY": "autogenerate-only", "RSA_PRIVATE_KEY_PATH": str(tmp_key)}
    try:
        done = await phase_exec.run(
            ["python3", "-m", "alembic", "revision", "--autogenerate", "-m", "initial schema", "--rev-id", "0001"],
            cwd=output_dir, env=env, timeout=120, text=True)
    finally:
        for tmp in (tmp_db, tmp_key):
            tmp.unlink(missing_ok=True)
    files = sorted(versions.glob("0001_*.py"))
    if done.returncode != 0 or not files:
        raise MigrationError(f"alembic could not generate the initial migration: {(done.stderr or '')[-600:]}")
    path = files[0]
    # The timestamp is the only non-deterministic line; pin it so identical input gives an identical file.
    path.write_text(re.sub(r"^Create Date: .*$", "Create Date: 2000-01-01 00:00:00", path.read_text(), flags=re.M))
    if "op.create_table" not in path.read_text():
        raise MigrationError("the generated initial migration creates no tables (no model registered on Base)")
    logger.info("[p04a] initial migration written: %s", path.name)
    return path
