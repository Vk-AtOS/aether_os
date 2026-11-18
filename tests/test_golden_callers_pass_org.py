"""KAN-92: phase callers must hand their org_id to get_golden_examples (else they only get platform examples)."""
import asyncio
from unittest.mock import AsyncMock, patch

from aether_os.phases.p04a_backend_codegen.crud_generator import _llm_models_and_schemas
from aether_os.phases.p05_frontend.helpers import _generate_domain_component


class _LLM:
    async def generate(self, *a, **k):
        raise RuntimeError("no model in tests")

    complete = generate


def test_p05_passes_org_id():
    with patch("aether_os.core.learning.golden_retriever.get_golden_examples", new=AsyncMock(return_value=[])) as g:
        try:
            asyncio.run(_generate_domain_component("saas", [], "P", accumulated_context={"org_id": "org-a"}))
        except Exception:  # LLM absent; only the retrieval call matters
            pass
    assert g.call_args.kwargs["org_id"] == "org-a"


def test_p04a_passes_org_id():
    with patch("aether_os.core.learning.golden_retriever.get_golden_examples", new=AsyncMock(return_value=[])) as g:
        try:
            asyncio.run(_llm_models_and_schemas(_LLM(), "P", "saas", [], "", {}, org_id="org-a"))
        except Exception:
            pass
    assert g.call_args.kwargs["org_id"] == "org-a"
