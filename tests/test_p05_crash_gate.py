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
    assert set(found) == {"src/components/DomainWidget.tsx", "src/pages/ProjectPage.tsx"}
    assert found["src/pages/ProjectPage.tsx"][0].startswith("TS2339: Property 'slice'")


def test_crashing_pages_are_rewritten_from_their_templates(tmp_path):
    (tmp_path / "src/pages").mkdir(parents=True)
    (tmp_path / "src/components").mkdir(parents=True)
    (tmp_path / "src/pages/ProjectPage.tsx").write_text("p.id.slice(0, 8)")
    (tmp_path / "src/pages/TaskPage.tsx").write_text("untouched")
    (tmp_path / "src/components/DomainWidget.tsx").write_text("<ClipboardList />")
    ir = DomainIR(domain="saas", app_name="T")
    ir.entities = [IREntity(name="Project", table="projects", fields=[IRField(name="name", type="string")])]
    ents = [{"table": "tasks", "name": "Task", "fields": [{"name": "status", "enum_values": ["todo", "done"]}]}]
    replaced = replace_crashing_pages(tmp_path, TSC, domain_ir=ir, entities=ents, route_map={}, domain="saas")
    assert sorted(replaced) == ["src/components/DomainWidget.tsx", "src/pages/ProjectPage.tsx"]
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
