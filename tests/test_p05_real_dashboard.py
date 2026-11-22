"""KAN-225: the generated dashboard shows /api/stats numbers and a widget for the app's own entities (run 20 fixture)."""
import asyncio
import re
import shutil
from pathlib import Path

import pytest

from aether_os.core.domain_ir import AetherType, DomainIR, IREntity, IRField
from aether_os.phases.p04a_backend_codegen.ir_generator_helpers import generate_stats_router
from aether_os.phases.p05_frontend import helpers
from aether_os.phases.p05_frontend.code_writer_parts.part02 import _generate_api
from aether_os.phases.p05_frontend.dashboard_stats import (
    ensure_real_stats, fallback_widget, hardcoded_counts_reason, stats_dashboard_tsx, widget_reason,
)

RUN20 = Path("/private/tmp/claude-501/-Users-apple/1a57cd35-efca-4a1e-b634-a519eaf0e507/scratchpad/run20")
needs_fixture = pytest.mark.skipif(not RUN20.exists(), reason="run 20 fixture not on this machine")

ENTITIES = [
    {"table": "users", "name": "User", "columns": ["email"], "fields": [{"name": "email", "type": "email"}]},
    {"table": "projects", "name": "Project", "columns": ["name", "status"],
     "fields": [{"name": "name", "type": "string"}, {"name": "status", "type": "string", "enum_values": ["active", "archived"]}]},
    {"table": "tasks", "name": "Task", "columns": ["title", "status", "due_date"],
     "fields": [{"name": "title", "type": "string"}, {"name": "status", "type": "string", "enum_values": ["todo", "doing", "done"]},
                {"name": "due_date", "type": AetherType.DATE}]},
]


def _ir():
    ir = DomainIR(domain="saas", app_name="Tasks")
    ir.entities = [
        IREntity(name="Project", table="projects", fields=[IRField(name="name", type="string")]),
        IREntity(name="Task", table="tasks", fields=[
            IRField(name="title", type="string"), IRField(name="status", type="string"),
            IRField(name="due_date", type=AetherType.DATE)]),
    ]
    return ir


@needs_fixture
def test_run20_dashboard_is_refused_and_replaced(tmp_path):
    src = tmp_path / "Dashboard.tsx"
    shutil.copy(RUN20 / "frontend/src/pages/Dashboard.tsx", src)
    code = src.read_text()
    assert "hard-coded" in hardcoded_counts_reason(code) or "stats" in hardcoded_counts_reason(code)
    new, replaced = ensure_real_stats(code, ENTITIES, "Team Task Tracker")
    assert replaced and hardcoded_counts_reason(new) is None
    assert "fetchStats" in new and "/lib/api" in new and "DOMAIN_WIDGET_SLOT" in new
    assert not re.search(r"\b(12|87|14)\b", new)                       # run 20's invented numbers are gone


def test_template_has_no_count_literals_and_cards_per_entity():
    code = stats_dashboard_tsx(ENTITIES, "Team Task Tracker")
    assert hardcoded_counts_reason(code) is None
    for key in ("total_projects", "total_tasks", "overdue_tasks"):
        assert f"'{key}'" in code
    assert "total_users" not in code and "overdue_projects" not in code
    assert "animate-pulse" in code and "No data yet" in code           # loading and empty states


def test_post_check_catches_each_kind_of_hardcoded_count():
    ok = "import { stats } from '@/lib/api'; const x = useQuery({queryFn: stats})"
    assert hardcoded_counts_reason(ok) is None
    assert hardcoded_counts_reason("const a = {totalTasks: 87}; stats()") is not None
    assert hardcoded_counts_reason("const k = [{ label: 'Rate', value: '78%' }]; stats()") is not None
    assert hardcoded_counts_reason("<div>Total 5</div>") is not None   # no /stats call at all


def test_saas_fallback_widget_is_not_another_domains_widget():
    kind, code = fallback_widget("saas", ENTITIES)
    low = code.lower()
    assert kind == "pipeline"                                          # Project/Task status enums, from the entity list
    assert "Project" in code and "stage_active" in code and "fetchStats" in code
    assert not any(w in low for w in ("shelf", "library", "books", "checked out", "mrr", "patient", "collection"))
    assert not re.search(r"(?<![-\w])\d{2,}\b", code)                  # no invented figures (class names like text-gray-500 excluded)


def test_generic_overview_when_no_status_enum_fits():
    kind, code = fallback_widget("library", [{"table": "widgets", "name": "Widget", "columns": ["name"]}])
    assert kind == "overview" and "total_widgets" in code and "'Widgets'" in code
    assert "shelf" not in code.lower()


def test_widget_with_invented_data_is_refused():
    assert widget_reason("const mockProjects = [{ id: 1 }]") is not None
    assert widget_reason(fallback_widget("saas", ENTITIES)[1]) is None


def test_failed_llm_uses_fallback_from_entities(monkeypatch):
    class Boom:
        async def call(self, *a, **k):
            raise RuntimeError("down")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setattr(helpers._llm_client, "get_llm_client", lambda: Boom())
    code = asyncio.run(helpers._generate_domain_component("saas", ENTITIES, "Tasks"))
    assert "Shelf" not in code and "stage_active" in code


def test_api_client_exposes_typed_stats_helper():
    api = _generate_api([{"table": "tasks"}], {})
    assert "export type Stats = Record<string, number>" in api and "export const stats = () =>" in api


def _run_stats(tmp_path, ir, rows):
    """Execute the generated stats.py against a tiny SQLite app."""
    pytest.importorskip("aiosqlite")
    import importlib.util
    import sys
    from sqlalchemy import Column, Date, Integer, String
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.orm import declarative_base
    Base = declarative_base()

    class Project(Base):
        __tablename__ = "projects"
        id = Column(Integer, primary_key=True)
        name = Column(String)

    class Task(Base):
        __tablename__ = "tasks"
        id = Column(Integer, primary_key=True)
        title = Column(String)
        status = Column(String)
        due_date = Column(Date)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")

    async def go():
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine)() as s:
            s.add_all([Project(name="p")] + [Task(**r) for r in rows])
            await s.commit()
        for name, mod in {"models": type(sys)("models"), "database": type(sys)("database"), "auth": type(sys)("auth")}.items():
            sys.modules[name] = mod
        sys.modules["models"].Project, sys.modules["models"].Task = Project, Task
        sys.modules["database"].get_db = lambda: None
        sys.modules["auth"].get_current_user = lambda: None
        f = tmp_path / "stats_gen.py"
        f.write_text(generate_stats_router(ir))
        spec = importlib.util.spec_from_file_location("stats_gen", f)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        async with async_sessionmaker(engine)() as s:
            return await m.get_stats(db=s, current_user={})
    return asyncio.run(go())


def test_stats_router_returns_counts_and_overdue(tmp_path):
    import datetime as dt
    past, future = dt.date.today() - dt.timedelta(days=3), dt.date.today() + dt.timedelta(days=3)
    out = _run_stats(tmp_path, _ir(), [
        {"title": "a", "status": "todo", "due_date": past},       # overdue
        {"title": "b", "status": "Done", "due_date": past},       # finished: not overdue
        {"title": "c", "status": "doing", "due_date": future},    # not yet due
        {"title": "d", "status": None, "due_date": past},         # no status yet, past due: overdue
        {"title": "e", "status": "todo", "due_date": None},       # no due date
    ])
    assert out["total_projects"] == 1 and out["total_tasks"] == 5 and out["overdue_tasks"] == 2
    assert "overdue_projects" not in out


def test_stats_router_without_due_field_has_no_overdue():
    ir = DomainIR(domain="x", app_name="x")
    ir.entities = [IREntity(name="Project", table="projects", fields=[IRField(name="status", type="string")])]
    code = generate_stats_router(ir)
    assert "overdue_" not in code
    compile(code, "stats.py", "exec")


# Production run 21 (22 Nov 2026): the model's Dashboard read /stats but with keys total_User / total_Project (entity
# names); the stats router serves total_projects (table names), so every card showed a dash. The post-check passed it.
_RUN21_ENTITIES = [
    {"name": "User", "table": "users", "fields": [{"name": "email", "type": "string"}]},
    {"name": "Project", "table": "projects", "fields": [{"name": "name", "type": "string"}]},
    {"name": "Task", "table": "tasks", "fields": [{"name": "status", "type": "string"}, {"name": "due_date", "type": "date"}]},
    {"name": "ProjectMember", "table": "project_members", "fields": [{"name": "role", "type": "string"}]},
]


def test_dashboard_reading_unserved_stats_keys_is_replaced():
    from aether_os.phases.p05_frontend.dashboard_stats import ensure_real_stats, hardcoded_counts_reason
    code = (Path(__file__).parent / "fixtures" / "run21" / "Dashboard.tsx").read_text()
    reason = hardcoded_counts_reason(code, _RUN21_ENTITIES)
    assert reason and "total_Project" in reason
    fixed, replaced = ensure_real_stats(code, _RUN21_ENTITIES, "Tracker")
    assert replaced and "total_projects" in fixed and "overdue_tasks" in fixed


def test_the_stats_template_passes_its_own_key_check():
    from aether_os.phases.p05_frontend.dashboard_stats import hardcoded_counts_reason, stats_dashboard_tsx
    assert hardcoded_counts_reason(stats_dashboard_tsx(_RUN21_ENTITIES, "Tracker"), _RUN21_ENTITIES) is None
