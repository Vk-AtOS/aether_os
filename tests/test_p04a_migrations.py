"""KAN-267 (D1): a generated backend is production-deployable.

Root cause: `alembic/versions` was empty and the app built its schema with `create_all` on every start, so a
production database could not be created by a migration; every start also seeded admin@example.com. The generator
now ships an initial migration, bootstrap.py (no create_all / seed in production), and no built-in admin password.
The app runs in a subprocess: it has modules named main, models, auth and database.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid

import pytest

from aether_os.phases.p04a_backend_codegen.templates_alembic import generate_initial_migration
from tests.test_p04a_generated_backend import generate

for _mod in ("slowapi", "aiosqlite", "jwt", "bcrypt", "email_validator", "httpx", "alembic", "asyncpg"):
    pytest.importorskip(_mod)

STRONG = "Str0ng-Admin-Pass-" + "x" * 4          # built at runtime: no fixed password in the repo
ENV_KEYS = ("DATABASE_URL", "ENVIRONMENT", "ADMIN_EMAIL", "ADMIN_PASSWORD", "SEED_DEMO_DATA", "SECRET_KEY")


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    """A generated backend with its initial migration, built once (the sandbox step runs with AETHER_SANDBOX=none)."""
    mp = pytest.MonkeyPatch()
    mp.setenv("AETHER_SANDBOX", "none")
    mp.setenv("AETHER_SANDBOX_ALLOW_NONE", "1")
    mp.setenv("ENVIRONMENT", "test")
    tmp = tmp_path_factory.mktemp("gen")
    _, out = generate(tmp, domain="crm", use_ir=True, monkeypatch=mp)
    asyncio.run(generate_initial_migration(out))
    mp.undo()
    (out / ".env").rename(out / ".env.dev")      # the dev .env carries a SQLite URL and an admin: each test sets its own env
    return out


def _env(**extra):
    env = {k: v for k, v in os.environ.items() if k not in ENV_KEYS}
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "SECRET_KEY": "t" * 32, **extra})
    return env


def alembic(app, *args, **env):
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=str(app), env=_env(**env),
                          capture_output=True, text=True, timeout=120)


def run_py(app, code, **env):
    return subprocess.run([sys.executable, "-c", code], cwd=str(app), env=_env(**env), capture_output=True,
                          text=True, timeout=120)


def sqlite_url(tmp_path, name="db.sqlite"):
    return f"sqlite+aiosqlite:///{tmp_path / name}"


_TABLES = r'''
import json, os, sqlite3, sys
con = sqlite3.connect(os.environ["DATABASE_URL"].split("///")[1])
print("RESULT " + json.dumps({"tables": sorted(r[0] for r in con.execute("select name from sqlite_master where type='table'")),
    "users": con.execute("select count(*) from users").fetchone()[0] if con.execute("select 1 from sqlite_master where name='users'").fetchone() else None}))
'''


def result(p):
    line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, f"no result:\n{p.stdout[-600:]}\n{p.stderr[-1500:]}"
    return json.loads(line[7:])


def test_initial_migration_is_a_committed_file_with_every_table(app):
    files = sorted((app / "alembic" / "versions").glob("*.py"))
    assert len(files) == 1, files
    text = files[0].read_text()
    for table in ("users", "customers", "invoices"):
        assert f"op.create_table('{table}'" in text
    assert "Create Date: 2000-01-01" in text      # pinned: the same input gives the same file
    assert not (app / "_autogen.db").exists() and not (app / "_autogen_key.pem").exists()


def test_migration_covers_every_table_the_app_creates(app, tmp_path):
    # create_all registers whatever main imports; the migration must hold the same tables.
    url = sqlite_url(tmp_path)
    assert alembic(app, "upgrade", "head", DATABASE_URL=url).returncode == 0
    code = ("import sys, os; sys.path.insert(0, 'src'); import main, database, json; "
            "print('RESULT ' + json.dumps(sorted(database.Base.metadata.tables)))")
    want = result(run_py(app, code, DATABASE_URL=url, ENVIRONMENT="test"))
    got = result(run_py(app, _TABLES, DATABASE_URL=url))["tables"]
    assert set(want) <= set(got), set(want) - set(got)
    assert "alembic_version" in got


def test_upgrade_head_works_on_an_empty_sqlite_and_downgrades(app, tmp_path):
    url = sqlite_url(tmp_path)
    p = alembic(app, "upgrade", "head", DATABASE_URL=url)
    assert p.returncode == 0, p.stderr[-1500:]
    assert alembic(app, "downgrade", "base", DATABASE_URL=url).returncode == 0
    assert "customers" not in result(run_py(app, _TABLES, DATABASE_URL=url))["tables"]


def test_upgrade_head_works_on_an_empty_postgres(app):
    import psycopg2
    host = os.environ.get("PGHOST", "/tmp")
    try:
        admin = psycopg2.connect(host=host, dbname="postgres", connect_timeout=3)
    except Exception as exc:
        pytest.skip(f"no local PostgreSQL reachable: {exc}")
    admin.autocommit = True
    name = "kan267_" + uuid.uuid4().hex[:10]
    admin.cursor().execute(f'CREATE DATABASE "{name}"')
    try:
        url = f"postgresql+asyncpg://{os.environ.get('PGUSER', os.environ.get('USER', 'postgres'))}@/{name}?host={host}"
        p = alembic(app, "upgrade", "head", DATABASE_URL=url)
        assert p.returncode == 0, p.stderr[-2000:]
        con = psycopg2.connect(host=host, dbname=name)
        cur = con.cursor()
        cur.execute("select table_name from information_schema.tables where table_schema='public'")
        assert {"users", "customers", "invoices", "alembic_version"} <= {r[0] for r in cur.fetchall()}
        con.close()
    finally:
        admin.cursor().execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.close()


_START = r'''
import json, os, sys
sys.path.insert(0, "src")
import main
from fastapi.testclient import TestClient
with TestClient(main.app, raise_server_exceptions=True) as c:
    print("RESULT " + json.dumps({"health": c.get("/health").status_code}))
'''


def test_production_start_runs_no_create_all_and_no_seed(app, tmp_path):
    url = sqlite_url(tmp_path)
    assert alembic(app, "upgrade", "head", DATABASE_URL=url).returncode == 0
    p = run_py(app, _START, DATABASE_URL=url, ENVIRONMENT="production")
    assert result(p)["health"] == 200
    assert result(run_py(app, _TABLES, DATABASE_URL=url))["users"] == 0     # no admin, no demo rows


def test_production_does_not_create_tables_for_an_unmigrated_database(app, tmp_path):
    url = sqlite_url(tmp_path)
    p = run_py(app, _START, DATABASE_URL=url, ENVIRONMENT="production")
    assert p.returncode != 0 and "alembic upgrade head" in p.stderr
    assert "users" not in result(run_py(app, _TABLES, DATABASE_URL=url))["tables"]   # nothing was created


def test_production_creates_only_the_admin_from_env_and_no_demo_rows(app, tmp_path):
    url = sqlite_url(tmp_path)
    assert alembic(app, "upgrade", "head", DATABASE_URL=url).returncode == 0
    run_py(app, _START, DATABASE_URL=url, ENVIRONMENT="production", ADMIN_EMAIL="owner@corp.test", ADMIN_PASSWORD=STRONG)
    assert result(run_py(app, _TABLES, DATABASE_URL=url))["users"] == 1
    count = ("import sqlite3, os, json; c = sqlite3.connect(os.environ['DATABASE_URL'].split('///')[1]); "
             "print('RESULT ' + json.dumps(c.execute('select count(*) from customers').fetchone()[0]))")
    assert result(run_py(app, count, DATABASE_URL=url)) == 0


@pytest.mark.parametrize("password,why", [("change-me", "default"), ("short1", "short"), ("Admin123", "short")])
def test_production_refuses_a_default_or_short_admin_password(app, tmp_path, password, why):
    url = sqlite_url(tmp_path)
    assert alembic(app, "upgrade", "head", DATABASE_URL=url).returncode == 0
    p = run_py(app, _START, DATABASE_URL=url, ENVIRONMENT="production", ADMIN_EMAIL="a@b.test", ADMIN_PASSWORD=password)
    assert p.returncode != 0 and "ADMIN_PASSWORD" in p.stderr, why
    assert result(run_py(app, _TABLES, DATABASE_URL=url))["users"] == 0


def test_production_refuses_a_missing_database_url(app):
    p = run_py(app, _START, ENVIRONMENT="production")
    assert p.returncode != 0 and "DATABASE_URL" in p.stderr


def test_development_creates_tables_but_seeds_only_when_asked(app, tmp_path):
    url = sqlite_url(tmp_path)
    run_py(app, _START, DATABASE_URL=url, ENVIRONMENT="development", ADMIN_EMAIL="a@b.test", ADMIN_PASSWORD="Dev-pass-long-enough")
    r = result(run_py(app, _TABLES, DATABASE_URL=url))
    assert "customers" in r["tables"] and r["users"] == 1
    count = ("import sqlite3, os, json; c = sqlite3.connect(os.environ['DATABASE_URL'].split('///')[1]); "
             "print('RESULT ' + json.dumps(c.execute('select count(*) from customers').fetchone()[0]))")
    assert result(run_py(app, count, DATABASE_URL=url)) == 0
    run_py(app, _START, DATABASE_URL=url, ENVIRONMENT="development", ADMIN_EMAIL="a@b.test", ADMIN_PASSWORD="Dev-pass-long-enough",
           SEED_DEMO_DATA="true")
    assert result(run_py(app, count, DATABASE_URL=url)) == 20
    run_py(app, _START, DATABASE_URL=url, ENVIRONMENT="development", ADMIN_EMAIL="a@b.test", ADMIN_PASSWORD="Dev-pass-long-enough",
           SEED_DEMO_DATA="true")
    assert result(run_py(app, count, DATABASE_URL=url)) == 20          # idempotent


def test_no_hard_coded_admin_password_and_env_example_is_safe(app):
    src = "\n".join(p.read_text() for p in (app / "src").rglob("*.py"))
    assert "admin_initial_password" not in src and "admin@example.com" not in src
    ex = (app / ".env.example").read_text()
    assert "DATABASE_URL=postgresql" in ex and "SEED_DEMO_DATA=false" in ex and "sqlite" not in ex
    assert "migrate" in (app / "Makefile").read_text() and "alembic upgrade head" in (app / "Dockerfile").read_text()


def test_export_ships_the_migrations_and_runs_them_on_start(app, tmp_path):
    import shutil
    from aether_os.core import project_export as pe
    ws = tmp_path / "ws"
    shutil.copytree(app, ws / "p04a_backend_codegen", ignore=shutil.ignore_patterns("*.db"))
    dest = tmp_path / "out"
    dest.mkdir()
    pe.assemble_export(ws, dest, "Demo")
    be = dest / "backend"
    assert (be / "alembic.ini").is_file() and (be / "alembic" / "env.py").is_file()
    assert list((be / "alembic" / "versions").glob("0001_*.py"))
    assert "alembic upgrade head" in (be / "Dockerfile").read_text()
    compose = (dest / "docker-compose.yml").read_text()
    assert "postgres" in compose and "ENVIRONMENT: production" in compose


_LOGS = r'''
import json, logging, os, sys, io
sys.path.insert(0, "src")
buf = io.StringIO(); logging.basicConfig(level=logging.INFO, stream=buf)
import main
from fastapi.testclient import TestClient
with TestClient(main.app, raise_server_exceptions=True) as c:
    pass
import sqlite3
con = sqlite3.connect(os.environ["DATABASE_URL"].split("///")[1])
print("RESULT " + json.dumps({"users": con.execute("select count(*) from users").fetchone()[0], "log": buf.getvalue()}))
'''


@pytest.mark.parametrize("password", ["change-me", "qwerty", "zq7-pw"])
def test_a_placeholder_or_short_admin_password_creates_no_admin_in_any_environment(app, tmp_path, password):
    r = result(run_py(app, _LOGS, DATABASE_URL=sqlite_url(tmp_path), ENVIRONMENT="development",
                      ADMIN_EMAIL="a@b.test", ADMIN_PASSWORD=password))
    assert r["users"] == 0
    assert "ADMIN_PASSWORD is" in r["log"] and password not in r["log"]      # names the rule, not the value


_RACE = r'''
import asyncio, json, logging, io, os, sys
sys.path.insert(0, "src")
buf = io.StringIO(); logging.basicConfig(level=logging.INFO, stream=buf)
import bootstrap, database
from sqlalchemy.exc import IntegrityError
async def lost_race(db): raise IntegrityError("INSERT INTO users", {"password_hash": "SECRETHASH"}, Exception("dup"))
async def boom(db): raise RuntimeError("SECRETHASH")
async def go(fn):
    bootstrap.ensure_admin = fn
    await bootstrap.run_startup(database.engine, database.Base)
asyncio.run(go(lost_race))
try:
    os.environ["ENVIRONMENT"] = "production"
    asyncio.run(go(boom))
except RuntimeError as e:
    err = str(e)
print("RESULT " + json.dumps({"log": buf.getvalue(), "err": err}))
'''


def test_bootstrap_failures_never_log_sql_parameters_and_a_lost_race_is_quiet(app, tmp_path):
    url = sqlite_url(tmp_path)
    assert alembic(app, "upgrade", "head", DATABASE_URL=url).returncode == 0
    r = result(run_py(app, _RACE, DATABASE_URL=url, ENVIRONMENT="development"))
    assert "SECRETHASH" not in r["log"] and "SECRETHASH" not in r["err"]
    assert "already created" in r["log"] and "RuntimeError" in r["log"]


def test_generated_engine_hides_sql_parameters(app):
    assert (app / "src" / "database.py").read_text().count("hide_parameters=True") == 2
