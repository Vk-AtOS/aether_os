"""KAN-109/KAN-100: the CI webhook and repair mode call run_repair correctly."""
import asyncio
from types import SimpleNamespace

from aether_os.phases.p08_cicd import pipeline, task_agent, webhook


def _req(root):
    return webhook.CIWebhookRequest(repo_name="r", branch="b", ci_job_name="j", ci_log="log", repo_root=str(root))


def test_call_graph_builds_for_repo(tmp_path):
    (tmp_path / "m.py").write_text("def a():\n    b()\n\ndef b():\n    pass\n")
    cg = webhook._build_call_graph_for_repo(str(tmp_path))
    assert cg is not None and cg.callees


def test_webhook_job_calls_run_repair_with_real_signature(monkeypatch, tmp_path):
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return SimpleNamespace(success=True, explanation="ok")

    monkeypatch.setattr(webhook, "run_repair", fake)
    asyncio.run(webhook._run_repair_async("j1", _req(tmp_path), None))
    assert seen["log_content"] == "log" and seen["root_dir"] == str(tmp_path)
    assert "ast_index" in seen and "historical_records" in seen


def test_run_repair_builds_index_when_none(tmp_path):
    (tmp_path / "m.py").write_text("def a():\n    pass\n")
    # no stack trace in the log: returns a failed result, but must not crash on ast_index=None
    r = pipeline.run_repair("nothing here", tmp_path, [], None)
    assert r.success is False


def test_repair_mode_success_is_reported(monkeypatch, tmp_path):
    async def fake_run(self, pi):
        return {"status": "repaired", "output_path": str(tmp_path), "confidence": 0.9}

    monkeypatch.setattr(task_agent.CICDAgent, "run", fake_run)
    res = asyncio.run(task_agent.run(SimpleNamespace(), [], tmp_path))
    assert res.success is True
