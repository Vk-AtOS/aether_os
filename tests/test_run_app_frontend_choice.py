"""Run-app serves the repaired frontend s04 produced, not p05's first draft (production run 20, 22 Nov 2026: the draft
was rebuilt, failed, and the Live App fell back to the API explorer)."""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "core" / "run_app" / "process_manager.py"


def test_the_repaired_frontend_is_tried_first():
    tree = ast.parse(SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_frontend_candidates" for t in node.targets):
            first = ast.unparse(node.value.elts[0])
            assert first == "root_dir / 'frontend'", first
            return
    raise AssertionError("_frontend_candidates not found")
