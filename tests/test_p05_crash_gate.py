"""Model-written pages that would crash at runtime are replaced by their template twins (runs 22 and 24: an unimported
icon, .slice() on a numeric id, a missing Select prop all bundled because vite does not type-check)."""
from aether_os.core.domain_ir import DomainIR, IREntity, IRField
from aether_os.phases.p05_frontend.crash_gate import crashing_files, replace_crashing_pages

# Real tsc lines from run 22/24 pages.
TSC = [
    "src/components/DomainWidget.tsx(66,12): error TS2552: Cannot find name 'ClipboardList'. Did you mean 'Clipboard'?",
    "src/pages/ProjectPage.tsx(166,74): error TS2339: Property 'slice' does not exist on type 'number'.",
    "src/pages/TaskPage.tsx(56,19): error TS2322: Type 'string | number' is not assignable to type 'string'.",
    "src/pages/customer/Home.tsx(3,1): error TS2304: Cannot find name 'Foo'.",
    "src/App.tsx(9,9): error TS2339: Property 'x' does not exist on type 'Y'.",
]


def test_only_crash_class_errors_in_model_written_surfaces_count():
    found = crashing_files(TSC)
    # customer Home joined the gated surfaces in KAN-255; TaskPage's TS2322 and App.tsx are not crash-class / not model-written
    assert set(found) == {"src/components/DomainWidget.tsx", "src/pages/ProjectPage.tsx", "src/pages/customer/Home.tsx"}
    assert found["src/pages/ProjectPage.tsx"][0].startswith("TS2339: Property 'slice'")


def test_crashing_pages_are_rewritten_from_their_templates(tmp_path):
    (tmp_path / "src/pages").mkdir(parents=True)
    (tmp_path / "src/components").mkdir(parents=True)
    (tmp_path / "src/pages/customer").mkdir()
    (tmp_path / "src/pages/customer/Home.tsx").write_text("<Foo />")
    (tmp_path / "src/pages/ProjectPage.tsx").write_text("p.id.slice(0, 8)")
    (tmp_path / "src/pages/TaskPage.tsx").write_text("untouched")
    (tmp_path / "src/components/DomainWidget.tsx").write_text("<ClipboardList />")
    ir = DomainIR(domain="saas", app_name="T")
    ir.entities = [IREntity(name="Project", table="projects", fields=[IRField(name="name", type="string")])]
    ents = [{"table": "tasks", "name": "Task", "fields": [{"name": "status", "enum_values": ["todo", "done"]}]}]
    replaced = replace_crashing_pages(tmp_path, TSC, domain_ir=ir, entities=ents, route_map={}, domain="saas")
    assert sorted(replaced) == ["src/components/DomainWidget.tsx", "src/pages/ProjectPage.tsx", "src/pages/customer/Home.tsx"]
    page = (tmp_path / "src/pages/ProjectPage.tsx").read_text()
    assert "export default function ProjectPage()" in page and ".slice(" not in page
    assert "ClipboardList" not in (tmp_path / "src/components/DomainWidget.tsx").read_text()
    assert (tmp_path / "src/pages/TaskPage.tsx").read_text() == "untouched"     # TS2322 alone does not crash


def test_a_page_without_a_template_twin_is_left_alone(tmp_path):
    (tmp_path / "src/pages").mkdir(parents=True)
    (tmp_path / "src/pages/ReportPage.tsx").write_text("x.y.z")
    tsc = ["src/pages/ReportPage.tsx(1,1): error TS2339: Property 'z' does not exist on type 'Y'."]
    assert replace_crashing_pages(tmp_path, tsc, entities=[], route_map={}) == []
    assert (tmp_path / "src/pages/ReportPage.tsx").read_text() == "x.y.z"


# --- run 27: tsc reports no type errors while any file fails to parse --------------------------------------------
import asyncio  # noqa: E402

from aether_os.phases.p05_frontend import crash_gate  # noqa: E402

RUN27_TSC = ["src/pages/customer/Home.tsx(129,47): error TS1382: Unexpected token. Did you mean `{'>'}` or `&gt;`?"]
RUN27_PER_FILE = RUN27_TSC + [
    "src/pages/ProjectPage.tsx(228,34): error TS2552: Cannot find name 'AlertDialogFooter'. Did you mean 'DialogFooter'?"]


def _project(tmp_path):
    fe = tmp_path / "frontend"
    (fe / "src/pages/customer").mkdir(parents=True)
    (fe / "src/pages/customer/Home.tsx").write_text("<div>>")
    (fe / "src/pages/ProjectPage.tsx").write_text("<AlertDialogFooter />")
    ir = DomainIR(domain="saas", app_name="T")
    ir.entities = [IREntity(name="Project", table="projects", fields=[IRField(name="name", type="string")])]
    (tmp_path / "p02b_domain_ir").mkdir()
    ir.save(tmp_path / "p02b_domain_ir" / "domain_ir.json")
    return fe


def test_plain_tsc_output_hides_the_crash_when_another_file_does_not_parse():
    # tsc reports only the syntax error: the gate sees (and now replaces) that file, but not ProjectPage's crash
    assert set(crashing_files(RUN27_TSC)) == {"src/pages/customer/Home.tsx"}


def test_gate_uses_per_file_diagnostics_and_loads_the_project_ir(tmp_path, monkeypatch):
    fe = _project(tmp_path)

    async def per_file(_dir):
        return RUN27_PER_FILE

    monkeypatch.setattr(crash_gate, "per_file_diagnostics", per_file)
    replaced = asyncio.run(crash_gate.run_crash_gate(fe, RUN27_TSC))      # no IR passed: s04 repair calls it so
    assert sorted(replaced) == ["src/pages/ProjectPage.tsx", "src/pages/customer/Home.tsx"]
    assert "AlertDialogFooter" not in (fe / "src/pages/ProjectPage.tsx").read_text()


def test_s04_repair_runs_the_gate_and_rebuilds_once(tmp_path, monkeypatch):
    from aether_os.phases.base import TaskResult
    from aether_os.stages.s04_frontend import repair

    calls = []

    async def loop(frontend_dir, max_rounds=3):
        calls.append(max_rounds)
        return {"success": True, "built": True, "tsc_errors": 0, "tsc_messages": [], "tsc_all": RUN27_TSC, "rounds": 1}

    async def gate(frontend_dir, tsc_lines):
        return ["src/pages/ProjectPage.tsx"]

    monkeypatch.setattr(repair, "run_build_loop", loop)
    monkeypatch.setattr(repair, "run_crash_gate", gate)
    out = asyncio.run(repair.repair_frontend_files(TaskResult(output_path=str(tmp_path), confidence=0.5, success=False,
                                                              metadata={}), tmp_path))
    assert calls == [2, 1] and out.success
