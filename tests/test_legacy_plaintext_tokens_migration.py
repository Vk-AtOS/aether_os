"""KAN-131: the last plaintext secrets (SCIM token, webhook signing secret, questionnaire share token) are moved to
their protected form by one migration, and no model or reader keeps a plaintext path."""
import hashlib
import importlib.util
from pathlib import Path

import bcrypt
import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from cryptography.fernet import Fernet

from aether_os.core import models
from aether_os.gateway.routers import scim_router

ROOT = Path(__file__).resolve().parents[1]
REV = "hash_legacy_plaintext_tokens"


def _migration():
    spec = importlib.util.spec_from_file_location(REV, ROOT / "alembic" / "versions" / f"{REV}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _old_db(tmp_path):
    eng = sa.create_engine(f"sqlite:///{tmp_path}/old.db")
    with eng.begin() as c:
        c.execute(sa.text("CREATE TABLE organisations (id VARCHAR(50) PRIMARY KEY, scim_token VARCHAR(128), "
                          "scim_token_hash VARCHAR(128), scim_token_lookup VARCHAR(64))"))
        c.execute(sa.text("CREATE TABLE webhooks (id VARCHAR(36) PRIMARY KEY, secret VARCHAR(255))"))
        c.execute(sa.text("CREATE TABLE questionnaire_sessions (id VARCHAR(36) PRIMARY KEY, access_token VARCHAR(64))"))
    return eng


def _upgrade(eng):
    with eng.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            _migration().upgrade()


def test_there_is_exactly_one_alembic_head_and_it_is_this_revision():
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    assert ScriptDirectory.from_config(cfg).get_heads() == [REV]


def test_migration_moves_every_plaintext_value_and_keeps_it_working(tmp_path, monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("AETHER_FIELD_KEY", key)
    fernet = Fernet(key.encode())
    already = fernet.encrypt(b"new-secret").decode()
    kept_hash = bcrypt.hashpw(b"rotated", bcrypt.gensalt(4)).decode()
    eng = _old_db(tmp_path)
    with eng.begin() as c:
        c.execute(sa.text("INSERT INTO organisations VALUES ('o1', 'plain-scim-token', NULL, NULL), "
                          "('o2', 'stale-plain', :h, 'lk'), ('o3', NULL, NULL, NULL)"), {"h": kept_hash})
        c.execute(sa.text("INSERT INTO webhooks VALUES ('w1', 'aabbcc-plain-hex'), ('w2', :c), ('w3', NULL)"), {"c": already})
        c.execute(sa.text("INSERT INTO questionnaire_sessions VALUES ('q1', 'plain-share-token'), ('q2', :h)"),
                  {"h": hashlib.sha256(b"other").hexdigest()})
    _upgrade(eng)
    _upgrade(eng)      # running it twice changes nothing more
    with eng.connect() as c:
        orgs = {r[0]: r[1:] for r in c.execute(sa.text(
            "SELECT id, scim_token, scim_token_hash, scim_token_lookup FROM organisations"))}
        hooks = dict(c.execute(sa.text("SELECT id, secret FROM webhooks")).fetchall())
        sessions = dict(c.execute(sa.text("SELECT id, access_token FROM questionnaire_sessions")).fetchall())
    assert [o[0] for o in orgs.values()] == [None, None, None]                       # no plaintext SCIM token left
    assert bcrypt.checkpw(b"plain-scim-token", orgs["o1"][1].encode())               # the old token still authenticates
    assert orgs["o1"][2] == hashlib.sha256(b"plain-scim-token").hexdigest()          # ... through the indexed lookup
    assert orgs["o2"][1:] == (kept_hash, "lk") and orgs["o3"][1:] == (None, None)    # a rotated org is not touched
    assert "plain" not in hooks["w1"] and fernet.decrypt(hooks["w1"].encode()) == b"aabbcc-plain-hex"
    assert hooks["w2"] == already and hooks["w3"] is None
    assert sessions == {"q1": hashlib.sha256(b"plain-share-token").hexdigest(), "q2": hashlib.sha256(b"other").hexdigest()}


def test_migration_refuses_to_guess_a_key_for_plaintext_webhook_secrets(tmp_path, monkeypatch):
    monkeypatch.delenv("AETHER_FIELD_KEY", raising=False)
    eng = _old_db(tmp_path)
    _upgrade(eng)                                    # nothing to encrypt: no key needed
    with eng.begin() as c:
        c.execute(sa.text("INSERT INTO webhooks VALUES ('w1', 'plain')"))
    with pytest.raises(RuntimeError, match="AETHER_FIELD_KEY"):
        _upgrade(eng)
    with eng.connect() as c:
        assert c.execute(sa.text("SELECT secret FROM webhooks")).scalar() == "plain"   # rolled back, not half done


def test_migration_runs_on_a_database_bootstrapped_from_the_models(tmp_path):
    eng = sa.create_engine(f"sqlite:///{tmp_path}/new.db")
    for table in ("organisations", "webhooks", "questionnaire_sessions", "runs"):
        models.Base.metadata.tables[table].create(eng)
    _upgrade(eng)


def test_no_model_or_reader_keeps_a_plaintext_path():
    assert "scim_token" not in models.Organisation.__table__.columns
    assert scim_router._match_org_token("tok", [("o1", bcrypt.hashpw(b"tok", bcrypt.gensalt(4)).decode())]) == "o1"
    assert scim_router._match_org_token("tok", [("o1", bcrypt.hashpw(b"other", bcrypt.gensalt(4)).decode())]) is None
