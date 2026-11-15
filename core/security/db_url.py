"""One validator for a database connection string typed by a user (schema import, connectors).

Root cause it replaces: callers sniffed the STRING (`startswith("sqlite:///")`, `not startswith("sqlite")`), but
SQLAlchemy parses it differently ("sqlite+pysqlite:///", "SQLITE://", "sqlite://?uri=true" with a file: URI), so a
string could pass the "not sqlite, so check the host" branch and still be a local file for the driver. Here the string
is parsed by SQLAlchemy FIRST and every decision is made on the parsed URL; the validated URL is what gets connected.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from sqlalchemy.engine import URL, make_url

from aether_os.core.security.safe_http import UnsafeURL, resolve_public

ALLOWED_DRIVERS = frozenset({
    "postgresql", "postgresql+psycopg2", "postgresql+psycopg",
    "mysql", "mysql+pymysql", "mysql+mysqldb",
    "sqlite", "sqlite+pysqlite",
})
_DEFAULT_PORT = {"postgresql": 5432, "mysql": 3306}
# the only query options a user may set: none of them reads a file or opens a socket path
_SAFE_QUERY = {"sslmode": {"disable", "allow", "prefer", "require"}, "connect_timeout": None, "charset": {"utf8", "utf8mb4"}}


def sqlite_base_dir() -> Path:
    return Path(os.environ.get("SCHEMA_IMPORT_SQLITE_DIR") or os.getcwd()).resolve()


def validate_db_url(connection_string: str, *, check_host: bool = True, sqlite_dir: Optional[Path] = None) -> URL:
    """The parsed, validated URL (drivername lower-cased). Raises ValueError. Blocking when check_host (DNS)."""
    if not isinstance(connection_string, str) or not connection_string.strip() or len(connection_string) > 2048:
        raise ValueError("invalid connection string")
    try:
        url = make_url(connection_string.strip())
    except Exception as exc:
        raise ValueError("invalid connection string") from exc
    driver = url.drivername.lower()
    if driver not in ALLOWED_DRIVERS:
        raise ValueError("unsupported database type")
    url = url.set(drivername=driver)
    if driver.split("+")[0] == "sqlite":
        return _sqlite(url, sqlite_dir)
    if not url.host:
        raise ValueError("connection string has no host")
    for k, v in url.query.items():
        allowed = _SAFE_QUERY.get(k, False)
        if allowed is False or not isinstance(v, str) or (allowed is not None and v not in allowed) \
                or (allowed is None and not v.isdigit()):
            raise ValueError(f"connection option {k!r} is not allowed")
    if check_host:
        port = url.port or _DEFAULT_PORT[driver.split("+")[0]]
        try:
            resolve_public(f"http://{url.host}:{port}/")
        except UnsafeURL as exc:
            raise ValueError(f"database host rejected: {exc}") from exc
    return url


def _sqlite(url: URL, base: Optional[Path]) -> URL:
    if url.query or url.host or url.username or url.password or url.port:
        raise ValueError("a SQLite connection string takes only a relative file path")
    db = url.database or ""
    if not db or ":" in db or "\\" in db or "\x00" in db or db.startswith(("/", "~")) or ".." in db.split("/"):
        raise ValueError("SQLite connection string must be a relative path inside the allowed folder (no '..', ':' or absolute path)")
    root = (base or sqlite_base_dir()).resolve()
    target = (root / db).resolve()     # resolves symlinks: a link out of the folder is refused below
    if root != target and root not in target.parents:
        raise ValueError("SQLite path is outside the allowed folder")
    return url.set(database=str(target))
