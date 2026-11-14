"""KAN-110: LLM diagnosis never sets process env; questionnaire ownership fails closed."""
import asyncio
import os

import pytest
from fastapi import HTTPException

from aether_os.core.workloop_monitor import WorkloopMonitor
from aether_os.gateway.routers import questionnaire_router as qr


def test_llm_diagnosis_cannot_change_the_process_environment(monkeypatch):
    monkeypatch.setenv("PRIMARY_LLM", "anthropic")
    m = WorkloopMonitor()
    asyncio.run(m._maybe_apply_fix({"auto_fixable": True, "fix_type": "env_var",
                                    "fix_action": "PRIMARY_LLM=ollama", "root_cause": "x"}))
    assert os.environ["PRIMARY_LLM"] == "anthropic"
    assert m._fix_log[-1]["type"] == "recommendation"


class _Run:
    def __init__(self, org): self.org_id = org


class _Db:
    def __init__(self, run): self.run = run
    async def execute(self, _q):
        run = self.run
        class R:
            def scalar_one_or_none(self): return run
        return R()


@pytest.mark.parametrize("user_org,run_org", [("", "org-b"), (None, "org-b"), ("org-a", None), ("org-a", "org-b")])
def test_ownership_check_fails_closed(user_org, run_org):
    with pytest.raises(HTTPException) as ei:
        asyncio.run(qr._verify_run_ownership("r1", {"org_id": user_org}, _Db(_Run(run_org))))
    assert ei.value.status_code == 403


def test_ownership_check_allows_the_owner():
    run = _Run("org-a")
    assert asyncio.run(qr._verify_run_ownership("r1", {"org_id": "org-a"}, _Db(run))) is run
