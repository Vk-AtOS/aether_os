"""Tests for src.dfle.ast_index."""

import tempfile
from pathlib import Path

import pytest

from src.dfle.ast_index import (
    FileIndexEntry,
    build_index,
    from_dict,
    to_dict,
    update_index,
)


def test_build_index_from_project() -> None:
    idx = build_index(".")
    assert "src/dfle/log_parser.py" in idx
    assert "src/dfle/ast_index.py" in idx
    entry = idx["src/dfle/ast_index.py"]
    assert "functions" in entry
    assert "classes" in entry
    func_names = [f["name"] for f in entry["functions"]]
    assert "build_index" in func_names
    assert "FileIndexEntry" in [c["name"] for c in entry["classes"]]


def test_file_index_entry_roundtrip() -> None:
    entry = FileIndexEntry(
        filename="foo.py",
        functions=[{"name": "bar", "line": 10}],
        classes=[{"name": "Baz", "line": 5}],
    )
    d = entry.to_dict()
    restored = FileIndexEntry.from_dict(d)
    assert restored.filename == entry.filename
    assert restored.functions == entry.functions
    assert restored.classes == entry.classes


def test_update_index_incremental() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.py").write_text("def f(): pass\n")
        (root / "b.py").write_text("class C: pass\n")

        idx = build_index(root)
        assert len(idx) == 2
        assert "a.py" in idx
        assert "b.py" in idx

        (root / "a.py").write_text("def f(): pass\ndef g(): pass\n")
        updated = update_index(idx, root, ["a.py"])
        assert len(updated) == 2
        assert len(updated["a.py"]["functions"]) == 2
        assert updated["b.py"] == idx["b.py"]


def test_update_index_removes_deleted_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "x.py").write_text("pass\n")
        idx = build_index(root)
        assert "x.py" in idx

        (root / "x.py").unlink()
        updated = update_index(idx, root, ["x.py"])
        assert "x.py" not in updated


def test_to_dict_from_dict_roundtrip() -> None:
    idx = {"a.py": {"filename": "a.py", "functions": [{"name": "f", "line": 1}], "classes": []}}
    d = to_dict(idx)
    restored = from_dict(d)
    assert restored == idx


def test_empty_root_returns_empty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        idx = build_index(root)
    assert idx == {}
