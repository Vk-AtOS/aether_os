"""KAN-49: a model provider that keeps answering 5xx is skipped instead of costing every call its retries."""
import pytest

import aether_os.core.model_router as router_mod
import aether_os.core.model_router_providers as providers_mod
from aether_os.core.errors import LLMUnavailable
from aether_os.tests.test_org_api_key_isolation import ORG_A, PLATFORM, FakeAnthropic, _call, keys  # noqa: F401
from aether_os.tests.test_router_breaker_scope import anthropic  # noqa: F401  (skips without the SDK)

pytestmark = pytest.mark.asyncio


class Flaky500(FakeAnthropic):
    async def create(self, messages, **kwargs):
        FakeAnthropic.calls.append((self.api_key, "500"))
        raise RuntimeError("500 Internal Server Error from upstream")


async def test_a_provider_that_keeps_answering_500_is_skipped_after_the_threshold(keys, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", PLATFORM)
    monkeypatch.setattr(anthropic, "AsyncAnthropic", Flaky500)
    monkeypatch.setenv("ROUTER_BREAKER_FAILURES", "3")

    async def no_sleep(_s):
        return None
    monkeypatch.setattr(router_mod.asyncio, "sleep", no_sleep)
    providers_mod._DEAD_PROVIDERS.clear()
    providers_mod._SERVER_FAILURES.clear()
    for _ in range(3):
        with pytest.raises(LLMUnavailable):
            await _call(ORG_A)
    attempts = len(FakeAnthropic.calls)
    with pytest.raises(LLMUnavailable):
        await _call(ORG_A)
    assert len(FakeAnthropic.calls) == attempts          # the open breaker kept the 4th call away from the provider
    providers_mod._DEAD_PROVIDERS.clear()
    providers_mod._SERVER_FAILURES.clear()
