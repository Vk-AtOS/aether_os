"""The Live App's frontend is built for /app-preview/ (production run 20, 22 Nov 2026: built for "/", the bundle 404ed
and the page was blank)."""
import ast
from pathlib import Path

from aether_os.core.run_app.build_checks import assets_outside_base

SRC = Path(__file__).resolve().parents[1] / "core" / "run_app" / "process_manager.py"


def test_run_app_build_passes_the_preview_base_path():
    tree = ast.parse(SRC.read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "child_env"]
    assert any(any(k.arg == "VITE_BASE_PATH" for k in c.keywords) for c in calls)


def test_assets_outside_base(tmp_path):
    idx = tmp_path / "index.html"
    idx.write_text('<link href="https://fonts.googleapis.com/x"><link rel="icon" href="/vite.svg">'
                   '<script src="/assets/index-G5.js"></script><link href="/assets/index-Cf.css">')
    assert assets_outside_base(idx, "/app-preview/") == ["/vite.svg", "/assets/index-G5.js", "/assets/index-Cf.css"]
    idx.write_text('<script src="/app-preview/assets/index.js"></script><link href="./x.css">'
                   '<link href="//cdn.example/x.css">')
    assert assets_outside_base(idx, "/app-preview/") == []
    assert assets_outside_base(tmp_path / "missing.html", "/app-preview/") == []


def test_a_dist_built_for_the_wrong_path_is_not_reused():
    """Run 20 relaunch: run-app reused a dist built for "/" ("Skipping frontend rebuild") and stayed blank."""
    tree = ast.parse(SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_dist_already_built" for t in node.targets):
            assert "assets_outside_base" in ast.unparse(node.value)
            return
    raise AssertionError("_dist_already_built not found")
