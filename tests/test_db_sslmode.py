"""A managed-database URL with ?sslmode= must reach asyncpg as `ssl` (seen on AWS RDS: TypeError: connect() got an
unexpected keyword argument 'sslmode'), while Alembic's sync URL keeps sslmode."""
from aether_os.core import db


def test_sslmode_is_moved_out_of_the_asyncpg_url():
    url, mode = db.asyncpg_url_and_ssl("postgresql+asyncpg://u:p%40ss@db.example:5432/app?sslmode=require&application_name=x")
    assert mode == "require"
    assert "sslmode" not in url and "application_name=x" in url and "u:p%40ss@" in url


def test_url_without_sslmode_is_unchanged():
    url = "postgresql+asyncpg://u:p@db:5432/app"
    assert db.asyncpg_url_and_ssl(url) == (url, None)


def test_the_engine_gets_ssl_as_a_connect_argument(monkeypatch):
    seen = {}
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example:5432/app?sslmode=verify-full")
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "create_async_engine", lambda url, **kw: seen.update(url=url, kw=kw) or object())
    monkeypatch.setattr(db, "install_postgres_breaker", lambda engine: None)
    db.get_engine()
    assert "sslmode" not in seen["url"] and seen["kw"]["connect_args"]["ssl"] == "verify-full"


def test_alembic_still_sees_sslmode(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example:5432/app?sslmode=require")
    assert db._build_db_url().endswith("?sslmode=require")
