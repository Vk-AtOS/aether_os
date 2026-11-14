"""Import and normalise a live database schema for use as p02 architecture input."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _validate_sqlite_path(connection_string: str) -> None:
    """SEC-C2: Reject SQLite paths that could read arbitrary local files.

    Blocks absolute paths (e.g. sqlite:////etc/passwd) and directory
    traversal sequences (e.g. sqlite:///../../.env) so this function
    cannot be used as a local-file read primitive.
    """
    # Strip the 'sqlite:///' prefix (3 slashes = relative, 4 = absolute)
    after_prefix = connection_string[len("sqlite:///"):]
    if after_prefix.startswith("/"):
        raise ValueError(
            "SQLite connection string must use a relative path, "
            "not an absolute path (SSRF/LFI prevention)"
        )
    if ".." in after_prefix.split("/"):
        raise ValueError(
            "SQLite connection string must not contain '..' path traversal "
            "(SSRF/LFI prevention)"
        )


def _assert_public_host(connection_string: str) -> None:
    """Raise ValueError unless the database host resolves only to public addresses."""
    from sqlalchemy.engine import make_url
    from aether_os.core.security.safe_http import UnsafeURL, resolve_public
    try:
        url = make_url(connection_string)
    except Exception as exc:
        raise ValueError(f"invalid connection string: {exc}") from exc
    if not url.host:
        raise ValueError("connection string has no host")
    try:
        resolve_public(f"http://{url.host}:{url.port or 80}/")
    except UnsafeURL as exc:
        raise ValueError(f"database host rejected: {exc}") from exc


async def import_schema(connection_string: str) -> Dict[str, Any]:
    """Connect to an existing database and return its schema in p02 db_schema format.

    Supports:
      - postgresql://user:pass@host:5432/dbname
      - mysql+pymysql://user:pass@host:3306/dbname
      - mysql://user:pass@host:3306/dbname
      - sqlite:///path/to/db.sqlite  (relative paths only — no leading / or ..)

    Returns:
      {
        "tables": [
          {
            "name": "patients",
            "columns": ["id", "name", "dob", "created_at"],
            "foreign_keys": [{"column": "doctor_id", "references": "doctors.id"}]
          },
          ...
        ]
      }

    On error returns: {"error": str(e), "tables": []}
    """
    # SEC-C2: validate SQLite paths before any I/O
    if connection_string.lower().startswith("sqlite:///"):
        try:
            _validate_sqlite_path(connection_string)
        except ValueError as ve:
            logger.warning("[schema_importer] rejected unsafe SQLite path: %s", ve)
            return {"error": str(ve), "tables": []}

    # SSRF: the host is typed by the caller; never let it be the platform's own network.
    if not connection_string.lower().startswith("sqlite"):
        try:
            await asyncio.to_thread(_assert_public_host, connection_string)
        except ValueError as ve:
            logger.warning("[schema_importer] rejected non-public database host: %s", ve)
            return {"error": str(ve), "tables": []}

    try:
        result = await asyncio.wait_for(
            _do_import(connection_string),
            timeout=10.0,
        )
        return result
    except asyncio.TimeoutError:
        msg = "Database connection timed out after 10 seconds"
        logger.warning("[schema_importer] %s", msg)
        return {"error": msg, "tables": []}
    except Exception as exc:
        logger.warning("[schema_importer] import failed: %s", exc)
        return {"error": str(exc), "tables": []}


async def _do_import(connection_string: str) -> Dict[str, Any]:
    """Run the synchronous SQLAlchemy inspection in a thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync_inspect, connection_string)


def _sync_inspect(connection_string: str) -> Dict[str, Any]:
    """Synchronous SQLAlchemy inspector — runs in thread pool."""
    from sqlalchemy import create_engine, inspect, text

    # Use a short connect_timeout where the driver supports it
    connect_args: dict = {}
    cs_lower = connection_string.lower()
    if cs_lower.startswith("postgresql"):
        connect_args["connect_timeout"] = 8
    elif cs_lower.startswith("mysql"):
        connect_args["connect_timeout"] = 8

    engine = create_engine(
        connection_string,
        connect_args=connect_args,
        pool_pre_ping=True,
        # Prevent connection pool from keeping idle connections open
        pool_size=1,
        max_overflow=0,
    )

    try:
        inspector = inspect(engine)
        table_names = inspector.get_table_names()

        tables = []
        for table_name in table_names:
            # Columns — just names; keep type as string for readability
            try:
                cols_info = inspector.get_columns(table_name)
                columns = [col["name"] for col in cols_info]
            except Exception as exc:
                logger.debug("Column inspection failed for %s: %s", table_name, exc)
                columns = []

            # Foreign keys
            foreign_keys: list[dict] = []
            try:
                fk_info = inspector.get_foreign_keys(table_name)
                for fk in fk_info:
                    # fk["constrained_columns"] is a list, fk["referred_table"] + fk["referred_columns"]
                    referred_table = fk.get("referred_table", "")
                    for local_col, ref_col in zip(
                        fk.get("constrained_columns", []),
                        fk.get("referred_columns", []),
                    ):
                        foreign_keys.append({
                            "column": local_col,
                            "references": f"{referred_table}.{ref_col}",
                        })
            except Exception as exc:
                logger.debug("FK inspection failed for %s: %s", table_name, exc)

            tables.append({
                "name": table_name,
                "columns": columns,
                "foreign_keys": foreign_keys,
            })

        return {"tables": tables}
    finally:
        engine.dispose()
