"""KAN-92: one org's golden builds must not reach another org (routes or LLM prompts)."""
import asyncio

from aether_os.core.db import get_session_factory
from aether_os.core.learning.golden_retriever import get_golden_examples
from aether_os.core.models import GoldenBuild


def _add(org_id, name):
    async def go():
        async with get_session_factory()() as s:
            s.add(GoldenBuild(run_id="r-" + name, org_id=org_id, domain="general",
                              project_name=name, p04_sample="SECRET-" + name))
            await s.commit()
    asyncio.run(go())


def test_routes_and_prompt_examples_are_org_scoped(gw):
    a, b = gw.register("golda"), gw.register("goldb")
    _add(a.org_id, "proj-a")
    _add(b.org_id, "proj-b")
    for path, key in (("/learning/golden-builds", "golden_builds"),):
        names = {x["project_name"] for x in gw.client.get(path, headers=a.auth).json()[key]}
        assert names == {"proj-a"}
    st = gw.client.get("/learning/stats", headers=b.auth).json()
    assert st["golden_builds"] == 1
    ex = asyncio.run(get_golden_examples("general", org_id=a.org_id))
    assert {e["project_name"] for e in ex} == {"proj-a"}
    assert asyncio.run(get_golden_examples("general")) == []
