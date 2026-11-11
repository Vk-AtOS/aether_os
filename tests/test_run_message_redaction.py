"""Run.message never stores credentials from exception text."""
from __future__ import annotations

import time

import pytest
import pytest_asyncio

import aether_os.core.db as db
from aether_os.core.audit.ledger import DecisionLedger
from aether_os.core.models import Run
from aether_os.core.security.redact import redact_secrets

AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"

SECRETS = [
    ("postgresql+asyncpg://aether:S3cr3tPw@db.internal:5432/aether_os", "S3cr3tPw"),
    ("https://user:hunter2@example.com/hook", "hunter2"),
    ("Authorization: Bearer abcDEF123456.tokenvalue", "abcDEF123456"),
    (f"401 for token {JWT}", JWT),
    ("invalid x-api-key sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWx", "sk-ant-api03"),
    ("OpenRouter rejected sk-or-v1-0123456789abcdef0123456789abcdef", "0123456789abcdef"),
    (f"boto: bad key {AWS_KEY}", AWS_KEY),
    ("platform key aesk_live_9f8e7d6c5b4a", "9f8e7d6c5b4a"),
    ("razorpay rzp_test_Ab12Cd34Ef56Gh", "Ab12Cd34Ef56Gh"),
    ("api_key=abcd1234efgh in request", "abcd1234efgh"),
    ('{"password": "correct horse"}', "correct"),
    ("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY99", "wJalrXUtnFEMI"),
    ("digest 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08", "9f86d081884c7d65"),
]


@pytest.mark.parametrize("text,secret", SECRETS)
def test_secret_is_removed(text, secret):
    out = redact_secrets(f"Stage s03_backend failed: {text}")
    assert secret not in out
    assert out.startswith("Stage s03_backend failed: ")
    assert "[redacted]" in out


@pytest.mark.parametrize("text", [
    "Stage s03_backend failed: ModuleNotFoundError: No module named 'schemas'",
    "run 3f2b8c1e-9a4d-4e7b-8c2a-1d5e6f7a8b9c: file /Users/apple/.aether_os/projects/x/p04_backend/src/main.py line 12",
    "Token budget exceeded: daily limit reached (max_tokens=8192)",
    "connect to http://127.0.0.1:11434/api/generate refused",
])
def test_ordinary_error_text_is_unchanged(text):
    assert redact_secrets(text) == text


def test_length_cap_and_none():
    assert len(redact_secrets("x " * 5000)) == 500
    assert len(redact_secrets("x " * 5000, limit=50)) == 50
    assert redact_secrets(None) == ""


@pytest_asyncio.fixture
async def run_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/runs.db")
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    engine = db.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    sf = db.get_session_factory()
    async with sf() as s:
        s.add(Run(id="run-1", command="factory: x", status="running", started_at=time.time()))
        await s.commit()
    yield sf
    await engine.dispose()


@pytest.mark.asyncio
async def test_stored_run_message_is_redacted_and_capped(run_db):
    """The path the pipeline uses: ledger.async_update_run_status(message=f"Stage X failed: {e}")."""
    exc = RuntimeError(
        "(asyncpg) could not connect to postgresql://aether:S3cr3tPw@10.0.0.5/aether_os "
        "with header Authorization: Bearer abcDEF123456789 " + "padding " * 200)
    await DecisionLedger().async_update_run_status("run-1", "failed", message=f"Stage s03_backend failed: {exc}")

    async with run_db() as s:
        run = await s.get(Run, "run-1")
    assert run.status == "failed"
    assert run.message.startswith("Stage s03_backend failed: (asyncpg) could not connect to postgresql://[redacted]@10.0.0.5")
    assert "S3cr3tPw" not in run.message and "abcDEF123456789" not in run.message
    assert len(run.message) <= 500


@pytest.mark.asyncio
async def test_status_update_without_message_leaves_message_alone(run_db):
    await DecisionLedger().async_update_run_status("run-1", "failed", message="first reason")
    await DecisionLedger().async_update_run_status("run-1", "cancelled")
    async with run_db() as s:
        assert (await s.get(Run, "run-1")).message == "first reason"
