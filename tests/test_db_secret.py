"""KAN-244: DB credentials come from Secrets Manager and survive an RDS password rotation (mocked boto3)."""
import json
import sys
import types
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from aether_os.core import db, db_secret


class FakeAuthError(Exception):
    sqlstate = "28P01"


@pytest.fixture
def secrets(monkeypatch):
    """boto3 stand-in whose secret can be rotated by changing `state['password']`."""
    state = {"password": "old pw/@:", "calls": 0}
    client = MagicMock()

    def get_secret_value(SecretId):
        state["calls"] += 1
        state["id"] = SecretId
        return {"SecretString": json.dumps({"username": "aether_user", "password": state["password"]})}

    client.get_secret_value.side_effect = get_secret_value
    fake_boto3 = types.SimpleNamespace(client=MagicMock(return_value=client))
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setenv("DATABASE_SECRET_ARN", "arn:aws:secretsmanager:eu-west-1:1:secret:rds")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://stale_user:stale@db.example:5432/aether_os")
    db_secret.reset_for_tests()
    yield state, fake_boto3
    db_secret.reset_for_tests()


def test_url_is_built_from_the_secret_keeping_host_and_database(secrets):
    state, boto3 = secrets
    url = db._build_db_url()
    assert url.startswith("postgresql+asyncpg://aether_user:") and "stale" not in url
    assert "@db.example:5432/aether_os" in url
    assert db.make_url(url).password == "old pw/@:"          # special characters survive quoting
    boto3.client.assert_called_with("secretsmanager", region_name="eu-west-1")
    assert state["id"].endswith("secret:rds")


def test_url_unchanged_without_secret_arn(monkeypatch):
    monkeypatch.delenv("DATABASE_SECRET_ARN", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/d")
    assert db._build_db_url() == "postgresql+asyncpg://u:p@h:5432/d"


def _connect(engine, fake_connect):
    sync = engine.sync_engine
    sync.dialect.connect = fake_connect
    cparams = {"user": "x", "password": "x", "host": "db.example"}
    for fn in sync.dialect.dispatch.do_connect:          # the way DefaultDialect.connect runs the listeners
        conn = fn(sync.dialect, None, (), cparams)
        if conn is not None:
            return conn


def test_auth_failure_rereads_secret_and_reconnects_once(secrets):
    state, _ = secrets
    engine = create_async_engine(db._build_db_url())
    db.install_postgres_breaker(engine)
    attempts = []

    def fake_connect(*_a, **kw):
        attempts.append(kw["password"])
        if kw["password"] != "new-pw":
            raise FakeAuthError("password authentication failed for user aether_user")
        return "CONN"

    state["password"] = "new-pw"      # rotated after startup, but our cache still has the old value
    db_secret._cache = ("aether_user", "old-pw")
    assert _connect(engine, fake_connect) == "CONN"
    assert attempts == ["old-pw", "new-pw"] and state["calls"] == 2   # startup read + one refresh


def test_second_auth_failure_is_raised_not_looped(secrets):
    engine = create_async_engine(db._build_db_url())
    db.install_postgres_breaker(engine)
    attempts = []

    def always_bad(*_a, **kw):
        attempts.append(1)
        raise FakeAuthError("password authentication failed")

    with pytest.raises(FakeAuthError):
        _connect(engine, always_bad)
    assert len(attempts) == 2


def test_other_errors_do_not_trigger_a_secret_read(secrets):
    state, _ = secrets
    engine = create_async_engine(db._build_db_url())
    db.install_postgres_breaker(engine)
    calls_after_startup = state["calls"]

    def refused(*_a, **_k):
        raise ConnectionRefusedError("refused")

    with pytest.raises(ConnectionRefusedError):
        _connect(engine, refused)
    assert state["calls"] == calls_after_startup
