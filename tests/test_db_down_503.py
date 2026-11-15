"""Postgres/Redis down must be a clean 503, never a 500 with the internal error.

Root cause: the only catch-all handler answered every Exception with 500, so a database that refused connections
(connection refused, pool timeout, server shutting down) looked like a bug in the application to clients, load
balancers (500 is not retried, 503 is) and the on-call alert (5xx-rate vs dependency-down). One handler at the app
root maps "the database is unreachable" to 503 + Retry-After and says nothing about the cause.
"""
import pytest
import sqlalchemy.exc as sa_exc
from sqlalchemy.ext.asyncio import AsyncSession



def _op_error():
    return sa_exc.OperationalError("SELECT 1", {}, ConnectionRefusedError("connect to 10.0.0.5:5432 refused"))


@pytest.mark.parametrize("exc", [
    _op_error(),
    sa_exc.InterfaceError("SELECT 1", {}, OSError("connection closed")),
    sa_exc.TimeoutError("QueuePool limit of size 3 overflow 7 reached, connection timed out"),
    ConnectionRefusedError("[Errno 111] connect call failed ('10.0.0.5', 5432)"),
])
def test_unreachable_database_on_an_authenticated_route_is_a_503_without_details(gw, monkeypatch, exc):
    me = gw.register("down")

    async def boom(self, *a, **k):
        raise exc
    monkeypatch.setattr(AsyncSession, "execute", boom)
    r = gw.client.get("/workspaces", headers=me.auth)
    assert r.status_code == 503, r.text
    assert r.headers["retry-after"]
    body = r.text
    assert "10.0.0.5" not in body and "5432" not in body and "Traceback" not in body
    assert r.json()["detail"]


def test_a_bad_query_or_an_ordinary_bug_is_not_treated_as_the_database_being_down():
    # A wrong query or a defect must stay a 500 (a 503 would make clients retry a request that can never succeed).
    from aether_os.core.db import DEPENDENCY_DOWN
    for exc in (ValueError("bug"), sa_exc.ProgrammingError("SELECT x", {}, Exception("no such column")),
                sa_exc.IntegrityError("INSERT", {}, Exception("duplicate key")), FileNotFoundError("x")):
        assert not isinstance(exc, DEPENDENCY_DOWN), type(exc)

