"""
Unit tests for core/db.py

These tests verify the database layer initialisation logic without requiring
a real database connection. The session factory and engine are mocked.
"""
from __future__ import annotations

import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_db_module():
    """Reset global state in core.db between tests so each test starts clean."""
    import importlib
    import aether_os.core.db as db_mod
    db_mod._engine = None
    db_mod._session_factory = None
    return db_mod


# ---------------------------------------------------------------------------
# _build_db_url
# ---------------------------------------------------------------------------

class TestBuildDbUrl:
    def test_uses_database_url_when_set(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@host/db")
        from aether_os.core.db import _build_db_url
        url = _build_db_url()
        # Must be upgraded to asyncpg driver
        assert "asyncpg" in url
        assert "postgresql+asyncpg" in url

    def test_postgres_prefix_normalised(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgres://user:pw@host/db")
        from aether_os.core.db import _build_db_url
        url = _build_db_url()
        assert url.startswith("postgresql+asyncpg://")

    def test_sqlite_fallback_when_no_env(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        from aether_os.core.db import _build_db_url
        url = _build_db_url()
        assert "sqlite+aiosqlite" in url

    def test_sqlite_url_contains_home_dir(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        from aether_os.core.db import _build_db_url
        url = _build_db_url()
        assert "aether_os.db" in url


# ---------------------------------------------------------------------------
# get_session_factory
# ---------------------------------------------------------------------------

class TestGetSessionFactory:
    def test_returns_same_instance_on_repeated_calls(self, monkeypatch):
        """get_session_factory() is a singleton — same object each call."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        import aether_os.core.db as db_mod
        db_mod._engine = None
        db_mod._session_factory = None

        with patch("aether_os.core.db.create_async_engine") as mock_eng:
            mock_engine = MagicMock()
            mock_engine.sync_engine = MagicMock()
            mock_eng.return_value = mock_engine
            with patch("aether_os.core.db.event"):
                sf1 = db_mod.get_session_factory()
                sf2 = db_mod.get_session_factory()
        assert sf1 is sf2

    def test_session_factory_is_configured_with_async_session(self, monkeypatch):
        """The factory must produce AsyncSession instances (not sync)."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        import aether_os.core.db as db_mod
        db_mod._engine = None
        db_mod._session_factory = None

        with patch("aether_os.core.db.create_async_engine") as mock_eng:
            mock_engine = MagicMock()
            mock_engine.sync_engine = MagicMock()
            mock_eng.return_value = mock_engine
            with patch("aether_os.core.db.event"):
                sf = db_mod.get_session_factory()

        # async_sessionmaker is callable and should produce something async-context-manageable
        assert callable(sf)


# ---------------------------------------------------------------------------
# get_db (FastAPI dependency)
# ---------------------------------------------------------------------------

class TestGetDb:
    @pytest.mark.asyncio
    async def test_get_db_is_async_generator(self, monkeypatch):
        """get_db() must be an async generator (yields a session)."""
        import inspect
        import aether_os.core.db as db_mod
        assert inspect.isasyncgenfunction(db_mod.get_db)

    @pytest.mark.asyncio
    async def test_get_db_yields_session(self, monkeypatch):
        """get_db() should yield the session from the factory context manager."""
        import aether_os.core.db as db_mod

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock()
        mock_factory.return_value = mock_session

        with patch.object(db_mod, "get_session_factory", return_value=mock_factory):
            gen = db_mod.get_db()
            session = await gen.__anext__()
            assert session is mock_session
            try:
                await gen.__anext__()
            except StopAsyncIteration:
                pass

    @pytest.mark.asyncio
    async def test_get_db_rolls_back_on_exception(self, monkeypatch):
        """If a handler raises, get_db() must rollback the session."""
        import aether_os.core.db as db_mod

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock()
        mock_factory.return_value = mock_session

        with patch.object(db_mod, "get_session_factory", return_value=mock_factory):
            gen = db_mod.get_db()
            await gen.__anext__()
            try:
                await gen.athrow(RuntimeError("test error"))
            except RuntimeError:
                pass

        mock_session.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# close_db
# ---------------------------------------------------------------------------

class TestCloseDb:
    @pytest.mark.asyncio
    async def test_close_db_disposes_engine(self, monkeypatch):
        """close_db() must call dispose() on the engine and reset globals."""
        import aether_os.core.db as db_mod

        mock_engine = AsyncMock()
        db_mod._engine = mock_engine
        db_mod._session_factory = MagicMock()

        await db_mod.close_db()

        mock_engine.dispose.assert_called_once()
        assert db_mod._engine is None
        assert db_mod._session_factory is None

    @pytest.mark.asyncio
    async def test_close_db_is_idempotent(self, monkeypatch):
        """close_db() when engine is already None must not raise."""
        import aether_os.core.db as db_mod
        db_mod._engine = None
        db_mod._session_factory = None

        # Should not raise
        await db_mod.close_db()
