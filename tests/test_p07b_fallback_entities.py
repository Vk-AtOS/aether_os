"""p07b's deterministic fallback: entity labels are normalised (run 11) and only entities the app really defines get
routes (run 14, 22 Nov 2026: it wrote `from schemas import UserCreate` into an app whose users live in auth.py)."""
from __future__ import annotations

from aether_os.phases.p07b_self_healing import quality_helpers

MODELS = "class Base: pass\nclass User(Base): pass\nclass Project(Base): pass\nclass Task(Base): pass\n"
SCHEMAS = ("class ProjectCreate: pass\nclass ProjectUpdate: pass\nclass TaskCreate: pass\nclass TaskUpdate: pass\n"
           "class TaskResponse: pass\n")


def _project(tmp_path):
    src = tmp_path / "p04_backend" / "backend_codegen" / "src"
    (src / "routers").mkdir(parents=True)
    (src / "models.py").write_text(MODELS)
    (src / "schemas.py").write_text(SCHEMAS)
    crud = src / "routers" / "crud.py"
    crud.write_text("all_routers = ['original']\n")
    return src, crud


def _capture(monkeypatch):
    seen = {}

    def fake_crud(entities, *a, **k):
        seen["entities"] = entities
        return "all_routers = []\n"

    import aether_os.phases.p04a_backend_codegen.crud_generator as gen
    monkeypatch.setattr(gen, "_fallback_crud_routers", fake_crud)
    return seen


def test_fallback_accepts_string_entities_and_skips_users_without_schemas(tmp_path, monkeypatch):
    _, crud = _project(tmp_path)
    seen = _capture(monkeypatch)
    quality_helpers.apply_deterministic_fallback(tmp_path, ["users", "projects", {"name": "Task"}, 7, ""],
                                                 {"project_name": "x"})
    assert seen["entities"] == [{"name": "Project", "table": "projects"}, {"name": "Task"}]
    assert crud.read_text() == "all_routers = []\n"


def test_fallback_leaves_crud_alone_when_no_entity_qualifies(tmp_path, monkeypatch):
    src, crud = _project(tmp_path)
    (src / "schemas.py").write_text("class Other: pass\n")
    seen = _capture(monkeypatch)
    quality_helpers.apply_deterministic_fallback(tmp_path, ["users", "projects"], {"project_name": "x"})
    assert "entities" not in seen and crud.read_text() == "all_routers = ['original']\n"


def test_entities_the_app_defines(tmp_path):
    src, _ = _project(tmp_path)
    ents = [{"name": "User"}, {"name": "Project"}, {"name": "Ghost"}]
    assert [e["name"] for e in quality_helpers.entities_the_app_defines(src, ents, need_schemas=True)] == ["Project"]
    assert [e["name"] for e in quality_helpers.entities_the_app_defines(src, ents, need_schemas=False)] == \
        ["User", "Project"]
