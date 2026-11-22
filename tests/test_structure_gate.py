"""VEL-37: the structure gate (import cycles, silent excepts, 600-line files) passes on the tree and fails on a new violation."""
import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_structure", ROOT / "scripts" / "ci" / "check_structure.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def test_tree_matches_baseline():
    assert gate.main([]) == 0


def test_baseline_only_holds_import_cycles():
    # Silent excepts and oversized files are all fixed; a new one must be fixed, never baselined.
    base = json.loads(gate.BASELINE.read_text())
    assert all(b.startswith("cycle::") for b in base), base


def _tree(tmp_path, files):
    for name, text in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return gate.collect(tmp_path)


def test_flags_silent_and_bare_excepts(tmp_path):
    found = _tree(tmp_path, {"pkg/a.py": "def f():\n    try:\n        1\n    except Exception:\n        pass\n"
                                         "def g():\n    try:\n        1\n    except:\n        raise\n"})
    assert "pkg/a.py::f::except-pass#1" in found and "pkg/a.py::g::bare except#1" in found


def test_logged_except_is_fine(tmp_path):
    assert _tree(tmp_path, {"pkg/a.py": "def f():\n    try:\n        1\n    except Exception as e:\n        print(e)\n"}) == []


def test_flags_oversized_file(tmp_path):
    assert _tree(tmp_path, {"pkg/big.py": "x = 1\n" * 601}) == ["size::pkg/big.py"]
    assert _tree(tmp_path / "ok", {"pkg/ok.py": "x = 1\n" * 600}) == []


def test_flags_import_cycle_but_not_function_level_import(tmp_path):
    cyc = _tree(tmp_path, {"a/__init__.py": "", "b/__init__.py": "",
                           "a/m.py": "from aether_os.b import n\n", "b/n.py": "from aether_os.a import m\n"})
    assert cyc == ["cycle::a <-> b"]
    ok = _tree(tmp_path / "ok", {"a/__init__.py": "", "b/__init__.py": "", "a/m.py": "from aether_os.b import n\n",
                                  "b/n.py": "def f():\n    from aether_os.a import m\n"})
    assert ok == []


def test_ci_runs_the_gate():
    assert "scripts/ci/check_structure.py" in (ROOT / ".github" / "workflows" / "ci.yml").read_text()
