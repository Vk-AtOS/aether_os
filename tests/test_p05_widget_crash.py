"""Production run 22 (22 Nov 2026): the model-written DomainWidget rendered <ClipboardList> without importing it. vite does
not type-check, so the build passed, and the admin landing page crashed into the error boundary right after sign-in."""
import asyncio

from aether_os.phases.p05_frontend.dashboard_stats import fallback_widget, undeclared_components, widget_reason
from aether_os.phases.p05_frontend.domain_assembler import generate_domain_widget

RUN22_WIDGET = """import { useQuery } from '@tanstack/react-query';
import { stats } from '@/lib/api';
import { ChevronRight, Users } from 'lucide-react';
// <Commented /> tags are ignored
export default function DomainWidget({ icon: Icon }: { icon: any }) {
  const { data } = useQuery<Stats>({ queryKey: ['stats'], queryFn: stats });
  if (!data) return <div><ClipboardList className="w-8 h-8" /></div>;
  return <div><Users /><ChevronRight /><Icon /></div>;
}
"""


def test_a_component_used_without_an_import_is_refused():
    assert undeclared_components(RUN22_WIDGET) == ["ClipboardList"]
    assert "ClipboardList" in widget_reason(RUN22_WIDGET)


def test_imported_destructured_and_generic_names_are_fine():
    ok = RUN22_WIDGET.replace("<ClipboardList className=\"w-8 h-8\" />", "<Users />")
    assert undeclared_components(ok) == [] and widget_reason(ok) is None


def test_the_generated_fallback_widgets_pass():
    ents = [{"table": "tasks", "name": "Task", "fields": [{"name": "status", "enum_values": ["todo", "done"]}]}]
    assert widget_reason(fallback_widget("saas", ents)[1]) is None
    assert widget_reason(fallback_widget("saas", [{"table": "notes", "name": "Note"}])[1]) is None


def test_the_widget_is_isolated_by_an_error_boundary(tmp_path):
    """Whatever the model writes, a widget that throws must not take the dashboard (and the sidebar) down."""
    (tmp_path / "components").mkdir()
    (tmp_path / "pages").mkdir()
    dash = tmp_path / "pages" / "Dashboard.tsx"
    dash.write_text("import { useQuery } from '@tanstack/react-query'\n<div>\n      {/* DOMAIN_WIDGET_SLOT */}\n</div>\n")

    async def widget(*_a, **_k):
        return "export default function DomainWidget() { return <div /> }"

    def write(path, code):
        path.write_text(code)

    ok = asyncio.run(generate_domain_widget(
        src_dir=tmp_path, domain="saas", entities=[], project_name="T", mem="", primary_hex="", secondary_hex="",
        background_hex="", surface_hex="", font_pairing="", border_radius="", density="", phase_start=0.0,
        phase_timeout=1e12, generate_domain_component_fn=widget, write_with_guard_fn=write))
    out = dash.read_text()
    assert ok
    assert "import { ErrorBoundary } from '../components/ErrorBoundary'" in out
    assert "<ErrorBoundary fallback={<></>}><DomainWidget /></ErrorBoundary>" in out
