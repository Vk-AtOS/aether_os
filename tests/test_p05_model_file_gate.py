"""KAN-255 / KAN-252 / KAN-251: every model-written surface is gated, every fallback is explained, type errors fail.

Run 909708e8 shipped a model-written Dashboard.tsx with a syntax error because the crash gate only knew *Page files.
Every completed build reported template_debt_pct 0.67-0.75 and nothing said which page fell back or why.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from aether_os.phases.p05_frontend import build_loop, llm_page_writer
from aether_os.phases.p05_frontend.crash_gate import crashing_files, replace_crashing_pages

ENTS = [{"table": "projects", "name": "Project", "columns": ["name"], "fields": [{"name": "name", "type": "string"}]}]


def _project(tmp_path, dual=True):
    (tmp_path / "src/pages/customer").mkdir(parents=True)
    (tmp_path / "src/components").mkdir()
    (tmp_path / "src/App.tsx").write_text("const adminLayoutRoute = 1" if dual else "const layoutRoute = 1")
    (tmp_path / "src/pages/Dashboard.tsx").write_text("export default function Dashboard() { return (<div> }")
    (tmp_path / "src/pages/customer/Home.tsx").write_text("export default function Home() { return <div>}> }")
    return tmp_path


def test_syntax_error_in_dashboard_and_customer_home_is_covered():
    lines = ["src/pages/Dashboard.tsx(1,60): error TS1005: '}' expected.",
             "src/pages/customer/Home.tsx(1,55): error TS1382: Unexpected token.",
             "src/pages/Dashboard.tsx(3,1): error TS2322: Type 'x' is not assignable to type 'y'.",
             "src/lib/helpers.ts(1,1): error TS1005: ';' expected."]
    assert set(crashing_files(lines)) == {"src/pages/Dashboard.tsx", "src/pages/customer/Home.tsx"}  # no twin for helpers.ts


def test_unparsable_dashboard_and_home_are_rewritten_from_templates(tmp_path):
    fe = _project(tmp_path)
    lines = ["src/pages/Dashboard.tsx(1,60): error TS1005: '}' expected.",
             "src/pages/customer/Home.tsx(1,55): error TS1382: Unexpected token."]
    replaced = replace_crashing_pages(fe, lines, entities=ENTS, domain="saas")
    assert sorted(replaced) == ["src/pages/Dashboard.tsx", "src/pages/customer/Home.tsx"]
    dash = (fe / "src/pages/Dashboard.tsx").read_text()
    assert "export default function Dashboard" in dash and "to='/admin/projects'" in dash   # dual portal: admin prefix
    assert "export default function Home" in (fe / "src/pages/customer/Home.tsx").read_text()


def test_any_type_error_replaces_a_model_page_only_in_the_final_pass(tmp_path):
    fe = _project(tmp_path)
    line = ["src/pages/Dashboard.tsx(3,1): error TS2322: Type 'x' is not assignable to type 'y'."]
    assert replace_crashing_pages(fe, line, entities=ENTS, domain="saas") == []
    assert replace_crashing_pages(fe, line, entities=ENTS, domain="saas", all_errors=True) == ["src/pages/Dashboard.tsx"]
    # now the file IS the template: replacing it again would change nothing, so it is not reported as replaced
    assert replace_crashing_pages(fe, line, entities=ENTS, domain="saas", all_errors=True) == []


def test_remaining_type_errors_fail_the_build():
    out = build_loop._outcome(True, ["src/a.tsx(1,1): error TS2322: bad"], 3)
    assert out["built"] is True and out["success"] is False and out["tsc_errors"] == 1
    assert build_loop._outcome(True, [], 1)["success"] is True
    meta, issues = build_loop.result_summary(out)
    assert meta["type_check_ok"] is False and meta["build_ok"] is True and "build fails" in issues[0]


@pytest.mark.parametrize("reply,reason", [
    ("", "empty_reply"),
    ("just prose", "missing_export_default_or_return"),
    ("export default function XPage() { return <button form='nope'>x</button> }", 'defect: button bound to form "nope", which does not exist'),
    ("export default function XPage() { const m = useMutation({ mutationFn: f }); return null }",
     "1_mutation_without_onError"),
])
def test_every_entity_page_rejection_has_a_reason(monkeypatch, reply, reason):
    class Fake:
        async def call(self, prompt, **kw):
            return reply
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr("aether_os.core.llm.client.get_llm_client", lambda: Fake())
    fallbacks: dict = {}
    code = asyncio.run(llm_page_writer.write_entity_page_llm(
        entity={"table": "xs", "name": "X", "fields": ["id"]}, route_map={}, project_name="D", domain="saas",
        raw_input="", domain_ir=None, design_tokens={}, fallbacks=fallbacks))
    assert code is None and fallbacks == {"pages/XPage.tsx": reason}


def test_llm_error_and_dashboard_reasons_are_recorded(monkeypatch):
    class Boom:
        async def call(self, prompt, **kw):
            raise RuntimeError("provider down")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr("aether_os.core.llm.client.get_llm_client", lambda: Boom())
    fallbacks: dict = {}
    assert asyncio.run(llm_page_writer.write_dashboard_llm("saas", ENTS, "D", "", None, {}, fallbacks=fallbacks)) is None
    assert fallbacks == {"pages/Dashboard.tsx": "llm_error: provider down"}


def test_frontend_meta_records_page_fallbacks(tmp_path, monkeypatch):
    import aether_os.phases.p05_frontend.domain_assembler as da
    from tests.test_p05_generated_frontend import build_frontend

    async def refuse(**kw):
        kw["fallbacks"][f"pages/{kw['entity']['table']}"] = "timeout_120s" if "entity" in kw else "x"
        return None
    monkeypatch.setattr(da, "write_entity_page_llm", refuse)
    build_frontend(tmp_path, "crm", monkeypatch)
    meta = json.loads((tmp_path / "p05_frontend" / "frontend_meta.json").read_text())
    assert {v for k, v in meta["page_fallbacks"].items() if k.startswith("pages/") and k.endswith("s")} >= {"timeout_120s"}
    assert meta["page_fallbacks"]["pages/Dashboard.tsx"] == "test_env"     # no model in tests: said so, not silent
    assert meta["model_page_fallback_pct"] == 1.0


def test_entity_page_prompt_lists_the_ui_components_that_exist(monkeypatch):
    # The prompt named five components; the model invented the rest (AlertDialogFooter, run 27).
    prompts = []

    class Fake:
        async def call(self, prompt, **kw):
            prompts.append(prompt)
            return ""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr("aether_os.core.llm.client.get_llm_client", lambda: Fake())
    asyncio.run(llm_page_writer.write_entity_page_llm(
        entity={"table": "xs", "name": "X", "fields": ["id"]}, route_map={}, project_name="D", domain="saas",
        raw_input="", domain_ir=None, design_tokens={}))
    assert "Card: Card, CardHeader" in prompts[0] and "Modal: Modal" in prompts[0]
    assert "AlertDialogFooter" not in prompts[0]
