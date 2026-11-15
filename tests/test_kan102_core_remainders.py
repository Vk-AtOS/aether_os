"""KAN-102 items 6-8: council strict mode is honoured in production, a missing coverage figure is not 80%,
webhook deliveries are not garbage collected mid-retry."""
import asyncio
import gc

import pytest

from aether_os.core.intelligence.truth_engine import _coverage_percent


def test_missing_or_bad_coverage_is_not_80_percent():
    assert _coverage_percent({}) == 0.0
    assert _coverage_percent({"coverage_percent": "high"}) == 0.0
    assert _coverage_percent({"coverage_percent": 140}) == 0.0
    assert _coverage_percent({"coverage": [{"addressed": True}, {"addressed": False}, {"addressed": "yes"}]}) == 33.3
    assert _coverage_percent({"coverage_percent": 62}) == 62.0


def test_council_strict_is_the_default_in_production_and_the_run_hook_asks_it(monkeypatch):
    from aether_os.core.council.council import _is_strict
    monkeypatch.delenv("COUNCIL_STRICT_MODE", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert _is_strict() is True
    monkeypatch.setenv("COUNCIL_STRICT_MODE", "false")
    assert _is_strict() is False
    import inspect
    from aether_os.gateway.routers import factory_run_background as bg
    src = inspect.getsource(bg)
    assert "_is_strict()" in src and 'environ.get("COUNCIL_STRICT_MODE", "false")' not in src


@pytest.mark.asyncio
async def test_webhook_delivery_tasks_are_referenced_until_done(monkeypatch):
    from aether_os.core.webhooks import delivery
    done = asyncio.Event()

    async def slow(**kw):
        await asyncio.sleep(0.05)
        done.set()
        return True

    async def hooks(org, ev):
        return [{"url": "https://x.example", "secret": "s"}]
    monkeypatch.setattr(delivery, "_get_org_webhooks", hooks)
    monkeypatch.setattr(delivery._delivery, "send", slow)
    await delivery.deliver_event("o", "e", {})
    assert len(delivery._tasks) == 1
    gc.collect()
    await asyncio.wait_for(done.wait(), 2)
    await asyncio.sleep(0.05)
    assert not delivery._tasks
