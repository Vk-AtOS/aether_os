"""Tests for src.dfle.call_graph."""

import tempfile
from pathlib import Path

import pytest

from src.dfle.ast_index import build_index
from src.dfle.call_graph import CallGraph, build_call_graph


def test_build_call_graph() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.py").write_text(
            "def foo():\n"
            "    bar()\n"
            "    baz()\n"
            "def bar():\n"
            "    pass\n"
        )
        (root / "b.py").write_text(
            "def baz():\n"
            "    foo()\n"
        )

        idx = build_index(root)
        cg = build_call_graph(idx, root)

        assert len(cg.callees) >= 3
        # foo calls bar and baz
        foo_id = "a.py:1:foo"
        assert foo_id in cg.callees
        assert "bar" in cg.callees[foo_id]
        assert "baz" in cg.callees[foo_id]
        # baz calls foo
        baz_id = "b.py:1:baz"
        assert "foo" in cg.callees[baz_id]
        # callers: who calls foo? (baz does)
        assert baz_id in cg.callers_of("foo")
        # who calls bar? (foo does)
        assert foo_id in cg.callers_of("bar")


def test_lookup() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "m.py").write_text(
            "def outer():\n"
            "    inner()\n"
            "def inner():\n"
            "    pass\n"
        )
        idx = build_index(root)
        cg = build_call_graph(idx, root)

        outer_id = "m.py:1:outer"
        callers, callees = cg.lookup(outer_id)
        assert "inner" in callees
        assert cg.callees_of(outer_id) == callees
        assert cg.callers_of("inner") == [outer_id]


def test_to_dict_from_dict() -> None:
    cg = CallGraph(
        callees={"a:1:f": ["g"], "b:2:g": []},
        callers={"g": ["a:1:f"]},
    )
    d = cg.to_dict()
    restored = CallGraph.from_dict(d)
    assert restored.callees == cg.callees
    assert restored.callers == cg.callers


def test_lookup_by_name() -> None:
    cg = CallGraph(
        callees={"p/x.py:1:foo": ["bar"], "q/y.py:2:foo": []},
        callers={"bar": ["p/x.py:1:foo"]},
    )
    ids = cg.lookup_by_name("foo")
    assert len(ids) == 2
    assert "p/x.py:1:foo" in ids
    assert "q/y.py:2:foo" in ids
