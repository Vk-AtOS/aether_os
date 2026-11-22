"""The build fixer is shown the source around each error, so its find/replace patches can match (run 12, 22 Nov 2026)."""
from __future__ import annotations

from aether_os.core.codegen.patching import MAX_SOURCE_CHARS, build_prompt
from aether_os.phases.p05_frontend import build_loop as bl


def _project(tmp_path):
    pages = tmp_path / "src" / "pages"
    pages.mkdir(parents=True)
    (pages / "TaskPage.tsx").write_text("\n".join(f"line {n}" for n in range(1, 301)))
    (pages / "UserPage.tsx").write_text("const a = 1;\nconst b = <div>;\n")
    return tmp_path


def test_context_covers_tsc_and_vite_locations(tmp_path):
    root = _project(tmp_path)
    errors = ("src/pages/TaskPage.tsx(254,306): error TS17002: Expected corresponding JSX closing tag for 'svg'.\n"
              f"{root}/src/pages/UserPage.tsx:2:15: ERROR: Unexpected end of file")
    ctx = bl._error_context(root, errors)
    assert "--- src/pages/TaskPage.tsx (lines 242-266)" in ctx and "254| line 254" in ctx and "241| " not in ctx
    assert "--- src/pages/UserPage.tsx (lines 1-2)" in ctx and "2| const b = <div>;" in ctx


def test_context_ignores_paths_outside_the_project_and_missing_files(tmp_path):
    root = _project(tmp_path)
    assert bl._error_context(root, "../../etc/passwd.ts(1,1): error TS1\nsrc/nope.tsx(3,1): error TS2") == \
        "(no source located)"


def test_context_is_bounded(tmp_path):
    root = _project(tmp_path)
    (root / "src" / "pages" / "TaskPage.tsx").write_text("\n".join("x" * 2000 for _ in range(300)))
    assert len(bl._error_context(root, "src/pages/TaskPage.tsx(150,1): error TS1")) <= MAX_SOURCE_CHARS


def test_prompt_carries_errors_and_source():
    prompt = build_prompt("R", "E1", "S1")
    assert "E1" in prompt and "S1" in prompt and "copied exactly" in prompt
