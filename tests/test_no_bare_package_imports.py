"""Code inside the aether_os package must import itself as `aether_os.<pkg>`.

A bare `from stages...` / `from core...` only resolves when the process happens to start inside the package
directory. It worked in the prod container and broke every local build at s03 ("No module named 'stages'",
28 Nov e2e). Imports inside a try/except ImportError fallback are allowed.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP = {"core", "stages", "phases", "orchestrator", "gateway", "agents", "prime", "integrations"}
SCAN = ["core", "stages", "phases", "orchestrator", "gateway", "agents", "prime", "integrations"]


def _guarded_ids(tree: ast.AST) -> set:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            catches = [h for h in node.handlers if isinstance(h.type, ast.Name)
                       and h.type.id in ("ImportError", "ModuleNotFoundError")]
            for handler in catches:
                ids.update(id(n) for n in ast.walk(handler))
    return ids


def test_package_code_never_imports_itself_by_a_bare_name():
    bad = []
    for top in SCAN:
        for path in (ROOT / top).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            guarded = _guarded_ids(tree)
            for node in ast.walk(tree):
                if id(node) in guarded:
                    continue
                if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module \
                        and node.module.split(".")[0] in TOP:
                    bad.append(f"{path.relative_to(ROOT)}:{node.lineno} from {node.module}")
    assert not bad, "bare intra-package imports (use aether_os.<pkg>):\n" + "\n".join(bad)
