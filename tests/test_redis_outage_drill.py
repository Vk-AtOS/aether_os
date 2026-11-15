"""KAN-136: Redis outage drill, run as a test against the real gateway with a fake Redis that can be
switched off and on. Documents and pins the behaviour the runbook promises:

  * authenticated requests fail CLOSED with 503 + Retry-After while Redis is down (a revoked token
    must never be accepted just because the revocation list is unreachable);
  * health stays up (it must, or the orchestrator kills healthy pods during a Redis blip);
  * nothing needs a restart: the first request after Redis returns succeeds;
  * a revocation recorded before the outage is still honoured after it.
"""
import time

from aether_os.core import api_rate_limit
from aether_os.gateway import auth_refresh
from aether_os.tests.fake_redis import FakeRedis


def test_outage_fails_closed_then_recovers_without_a_restart(gw, monkeypatch):
    fake = FakeRedis()

    async def fake_redis():
        return fake

    async def fake_async_redis():
        return fake

    monkeypatch.setattr(auth_refresh, "_redis", fake_redis)
    monkeypatch.setattr(api_rate_limit, "_get_async_redis", fake_async_redis)
    monkeypatch.setattr(auth_refresh, "_verdicts", {})
    user = gw.register("drill")

    assert gw.client.get("/auth/my-orgs", headers=user.auth).status_code == 200      # normal

    fake.down = True                                                                  # --- outage ---
    auth_refresh._verdicts.clear()
    r = gw.client.get("/auth/my-orgs", headers=user.auth)
    assert r.status_code == 503 and r.headers.get("Retry-After")
    assert gw.client.get("/health").status_code == 200                                # liveness unaffected
    assert gw.client.post("/auth/login", json={"email": user.email, "password": gw.password}).status_code != 500

    fake.down = False                                                                 # --- recovery ---
    t0 = time.monotonic()
    assert gw.client.get("/auth/my-orgs", headers=user.auth).status_code == 200
    assert time.monotonic() - t0 < 5


def test_a_revocation_made_before_the_outage_still_holds_after_it(gw, monkeypatch):
    fake = FakeRedis()

    async def fake_redis():
        return fake

    monkeypatch.setattr(auth_refresh, "_redis", fake_redis)
    monkeypatch.setattr(api_rate_limit, "_get_async_redis", lambda: fake_redis())
    monkeypatch.setattr(auth_refresh, "_verdicts", {})
    user = gw.register("drill2")
    assert gw.client.post("/auth/logout", headers=user.auth).status_code == 200
    fake.down = True
    auth_refresh._verdicts.clear()
    assert gw.client.get("/auth/my-orgs", headers=user.auth).status_code == 503
    fake.down = False
    auth_refresh._verdicts.clear()
    assert gw.client.get("/auth/my-orgs", headers=user.auth).status_code == 401       # revoked, not resurrected
