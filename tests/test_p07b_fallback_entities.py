"""p07b's deterministic fallback takes entity names as plain strings (acceptance run 11, 22 Nov 2026: it crashed with
"'str' object has no attribute 'get'", so Stage 7 never got its structurally correct baseline)."""
from __future__ import annotations

from aether_os.phases.p07b_self_healing import quality_helpers


def test_fallback_accepts_string_entities(tmp_path, monkeypatch):
    src = tmp_path / "p04_backend" / "backend_codegen" / "src"
    (src / "routers").mkdir(parents=True)
    crud = src / "routers" / "crud.py"
    crud.write_text("broken = (\n")
    seen = {}

    def fake_crud(entities, *a, **k):
        seen["entities"] = entities
        return "all_routers = []\n"

    import aether_os.phases.p04a_backend_codegen.crud_generator as gen
    monkeypatch.setattr(gen, "_fallback_crud_routers", fake_crud)
    quality_helpers.apply_deterministic_fallback(tmp_path, ["Task", {"name": "Project"}, 7, ""], {"project_name": "x"})
    assert seen["entities"] == [{"name": "Task", "table": "tasks"}, {"name": "Project"}]
    assert crud.read_text() == "all_routers = []\n"
