"""The Live App frontend's VITE_API_URL is the preview prefix without /api (production run 20, 22 Nov 2026: the sign-in
posted to /app-preview/api/api/auth/login and failed with 405)."""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "core" / "run_app" / "process_manager.py"


def test_env_production_has_no_api_suffix():
    tree = ast.parse(SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_correct_env" for t in node.targets):
            assert ast.literal_eval(node.value) == "VITE_API_URL=/app-preview\n"
            return
    raise AssertionError("_correct_env not found")
