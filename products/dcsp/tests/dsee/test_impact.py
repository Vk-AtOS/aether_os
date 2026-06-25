"""Tests for src.dsee.impact."""

import pytest
from src.dsee.impact import simulate_impact, ImpactResult
from src.dfle.call_graph import CallGraph


def test_impact_exported_removal():
    ast_index = {
        "main.py": {
            "functions": [
                {"name": "foo", "line": 1},
                {"name": "_private", "line": 5}
            ]
        }
    }
    cg = CallGraph()
    # Remove public function 'foo'
    patch = (
        "--- main.py\n"
        "+++ main.py\n"
        "@@ -1,1 +1,0 @@\n"
        "-def foo():\n"
    )
    res = simulate_impact(patch, ast_index, cg)
    assert res.safe is False
    assert res.risk_level == "risky"
    assert any("Public function 'foo' removed" in r for r in res.reasons)


def test_impact_signature_change():
    ast_index = {
        "main.py": {
            "functions": [{"name": "foo", "line": 1}]
        }
    }
    cg = CallGraph()
    # Change signature: add parameter
    patch = (
        "--- main.py\n"
        "+++ main.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-def foo(a):\n"
        "+def foo(a, b):\n"
    )
    res = simulate_impact(patch, ast_index, cg)
    assert res.safe is False
    assert res.risk_level == "risky"
    assert any("signature modified" in r for r in res.reasons)


def test_impact_line_shift():
    ast_index = {
        "main.py": {
            "functions": [{"name": "foo", "line": 10}]
        }
    }
    cg = CallGraph()
    # Add 10 lines at the top, shifting 'foo' from 10 to 20
    patch = (
        "--- main.py\n"
        "+++ main.py\n"
        "@@ -1,1 +1,11 @@\n"
        "+# padding\n"
        "+# padding\n"
        "+# padding\n"
        "+# padding\n"
        "+# padding\n"
        "+# padding\n"
        "+# padding\n"
        "+# padding\n"
        "+# padding\n"
        "+# padding\n"
        " def some_context():\n"
    )
    res = simulate_impact(patch, ast_index, cg)
    assert res.safe is False
    assert res.risk_level == "risky"
    assert any("Significant line shift (10)" in r for r in res.reasons)


def test_impact_new_function():
    ast_index = {"main.py": {"functions": []}}
    cg = CallGraph()
    # Introduce a new function
    patch = (
        "--- main.py\n"
        "+++ main.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+def new_func():\n"
        "+    pass\n"
    )
    res = simulate_impact(patch, ast_index, cg)
    assert res.safe is True
    assert res.risk_level == "minor"
    assert any("New function 'new_func' introduced" in r for r in res.reasons)


def test_impact_ripple():
    ast_index = {
        "lib.py": {"functions": [{"name": "utility", "line": 1}]},
        "app.py": {"functions": [{"name": "run", "line": 1}]}
    }
    # app.run calls lib.utility
    cg = CallGraph(
        callees={"app.py:1:run": ["utility"]},
        callers={"utility": ["app.py:1:run"]}
    )
    # Modify utility's body internally
    patch = (
        "--- lib.py\n"
        "+++ lib.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def utility():\n"
        "-    return 1\n"
        "+    return 2\n"
    )
    res = simulate_impact(patch, ast_index, cg)
    # ripple count should be 1 (run calls utility)
    assert res.dependency_ripple_count == 1
    assert any("Dependency ripple: 1" in r for r in res.reasons)


def test_impact_safe():
    ast_index = {
        "main.py": {"functions": [{"name": "foo", "line": 1}]}
    }
    cg = CallGraph()
    # Internal change in body, no signature change, no big shift
    patch = (
        "--- main.py\n"
        "+++ main.py\n"
        "@@ -2,1 +2,1 @@\n"
        "-    x = 1\n"
        "+    x = 2\n"
    )
    res = simulate_impact(patch, ast_index, cg)
    assert res.safe is True
    assert res.risk_level == "safe"
    assert res.dependency_ripple_count == 0


def test_impact_transitive_ripple():
    ast_index = {
        "lib.py": {"functions": [{"name": "base", "line": 1}]},
        "mid.py": {"functions": [{"name": "middle", "line": 1}]},
        "top.py": {"functions": [{"name": "caller", "line": 1}]}
    }
    # caller -> middle -> base
    cg = CallGraph(
        callees={
            "top.py:1:caller": ["middle"],
            "mid.py:1:middle": ["base"]
        },
        callers={
            "middle": ["top.py:1:caller"],
            "base": ["mid.py:1:middle"]
        }
    )
    # Modify base
    patch = (
        "--- lib.py\n"
        "+++ lib.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def base():\n"
        "-    pass\n"
        "+    print(1)\n"
    )
    res = simulate_impact(patch, ast_index, cg)
    # middle calls base, caller calls middle. Both are impacted.
    assert res.dependency_ripple_count == 2
    assert any("Dependency ripple: 2" in r for r in res.reasons)
