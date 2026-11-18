import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

try:
    from aether_os.core.db import Base, _build_db_url
    from aether_os.core import schema_ddl
except ModuleNotFoundError:
    from core.db import Base, _build_db_url
    from core import schema_ddl
schema_ddl.register_models()   # every model module, or autogenerate proposes dropping the tables it did not see
target_metadata = Base.metadata


def _sync_url(url: str) -> str:
    """Strip async driver prefix so alembic can use the sync driver."""
    return (
        url
        .replace("+aiosqlite", "")
        .replace("+asyncpg", "")
        .replace("postgresql+asyncpg://", "postgresql://")
    )


def run_migrations_offline() -> None:
    url = _sync_url(_build_db_url())
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _sync_url(_build_db_url())
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = url

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        if connection.dialect.name == "postgresql":
            # Several revision ids here are longer than Alembic's default VARCHAR(32) version column; without
            # this a replay from an empty database fails with StringDataRightTruncation mid-history.
            connection.exec_driver_sql("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(255) NOT NULL, "
                                       "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))")
            connection.exec_driver_sql("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)")
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
