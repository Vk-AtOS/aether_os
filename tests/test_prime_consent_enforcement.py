"""KAN-228: no collector and no read of learned data can skip prime.consent.allowed().

Three locks, each with a check that fails the build:
  * the table prime_learned_items is referenced only by prime/learned.py (and its model), so there is no other way in;
  * in prime/learned.py every function that stores a row or reads whole rows calls consent.allowed (directly or via
    _drop_withdrawn, which does);
  * collector modules (prime/collectors/*.py) only define functions registered with @collector, and never touch the
    session, the table, learned.record or the consent switches; collectors.run() checks consent before calling one.
The scanners are tested on bad examples too, so a scanner that stops finding anything also fails."""
# ruff: noqa: F811
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from aether_os.prime import collectors, consent, learned
from aether_os.prime.collectors import Learned, collector
from aether_os.tests.prime_helpers import DAVE, ORG, svc  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
TABLE_OWNERS = {"prime/learned.py", "prime/models.py"}
GUARDS = {"allowed", "_drop_withdrawn"}
FORBIDDEN_IN_COLLECTORS = {"PrimeLearnedItem", "PrimeConsent", "get_session_factory", "learned", "record",
                           "set_switch", "AsyncSession"}
SKIP = {"tests", "node_modules", "__pycache__", ".git", "dashboard", "venv", ".venv"}


def _python_files():
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT)
        if not SKIP & set(rel.parts):
            yield rel.as_posix(), p


def _names(node) -> set:
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.alias):
            out.update(n.name.split(".") + ([n.asname] if n.asname else []))
    return out


def _calls(node) -> set:
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            out.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
    return out


def table_users(files) -> list:
    """Modules other than the owners that name the learned-items model."""
    return [rel for rel, text in files if rel not in TABLE_OWNERS and "PrimeLearnedItem" in _names(ast.parse(text))]


def unguarded(source: str) -> list:
    """Functions that insert a PrimeLearnedItem or select whole rows without calling a consent guard."""
    bad = []
    for fn in ast.walk(ast.parse(source)):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.name in GUARDS:
            continue
        touches = any(isinstance(n, ast.Call) and (
            getattr(n.func, "id", "") == "PrimeLearnedItem"
            or (getattr(n.func, "id", "") == "select" and any(getattr(a, "id", "") == "PrimeLearnedItem" for a in n.args)))
            for n in ast.walk(fn))
        if touches and not GUARDS & _calls(fn):
            bad.append(fn.name)
    return bad


def collector_violations(source: str) -> list:
    """A collector module may only hold @collector-registered public functions and must not store anything itself."""
    tree = ast.parse(source)
    bad = [f"uses {n}" for n in sorted(FORBIDDEN_IN_COLLECTORS & _names(tree))]
    for fn in tree.body:
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and not fn.name.startswith("_"):
            registered = any(isinstance(d, ast.Call) and getattr(d.func, "id", getattr(d.func, "attr", "")) == "collector"
                             for d in fn.decorator_list)
            if not registered:
                bad.append(f"{fn.name} is not registered with @collector")
    return bad


def test_only_learned_py_touches_the_learned_items_table():
    assert table_users((rel, p.read_text()) for rel, p in _python_files()) == []
    assert table_users([("prime/sneaky.py", "from x import PrimeLearnedItem\n")]) == ["prime/sneaky.py"]


def test_every_store_or_read_in_learned_py_checks_consent():
    assert unguarded((ROOT / "prime" / "learned.py").read_text()) == []
    bad = ("async def leak(o, u):\n    return select(PrimeLearnedItem).where(1)\n"
           "async def put(o, u):\n    s.add(PrimeLearnedItem(org_id=o))\n"
           "async def ok(o, u):\n    if not await consent.allowed(o, u, 'git'):\n        return []\n"
           "    return select(PrimeLearnedItem)\n")
    assert unguarded(bad) == ["leak", "put"]


def test_collector_modules_cannot_skip_the_consent_check():
    modules = [p for p in (ROOT / "prime" / "collectors").glob("*.py") if p.name != "__init__.py"]
    assert {p.name: collector_violations(p.read_text()) for p in modules} == {p.name: [] for p in modules}
    assert collectors.load_all() is collectors.REGISTRY
    good = "from aether_os.prime.collectors import collector\n@collector('git_commits', 'git')\nasync def commits(o, u):\n    return []\n"
    assert collector_violations(good) == []
    bad = ("from aether_os.prime import learned\nasync def commits(o, u):\n"
           "    await learned.record(o, u, 'git', 'commit', 'x')\n")
    assert collector_violations(bad) == ["uses learned", "uses record", "commits is not registered with @collector"]


def test_a_collector_needs_a_known_source_and_a_unique_name(monkeypatch):
    monkeypatch.setattr(collectors, "REGISTRY", {})
    with pytest.raises(ValueError):
        collector("keys", "keystrokes")
    collector("c", "git")(lambda o, u: None)
    with pytest.raises(ValueError):
        collector("c", "jira")(lambda o, u: None)


@pytest.mark.asyncio
async def test_run_calls_a_collector_only_with_consent(svc, monkeypatch):
    called = []

    async def commits(org_id, user_id):
        called.append(user_id)
        return [Learned("commit", "fixed login for dave@a.test", {"repo": "aether"})]
    monkeypatch.setattr(collectors, "REGISTRY", {})
    collector("git_commits", "git")(commits)
    assert await collectors.run("git_commits", ORG, DAVE) == 0 and called == []     # default off: never called
    await consent.set_switch(ORG, DAVE, "all", True, DAVE, consent.NOTICE_VERSION)
    assert await collectors.run("git_commits", ORG, DAVE) == 0 and called == []     # the source itself is still off
    await consent.set_switch(ORG, DAVE, "git", True, DAVE, consent.NOTICE_VERSION)
    assert await collectors.run("git_commits", ORG, DAVE) == 1 and called == [DAVE]
    got = await learned.usable(ORG, DAVE, "git")
    assert len(got) == 1 and "dave@a.test" not in got[0]["summary"]                  # pseudonymised before storage
    await consent.set_switch(ORG, DAVE, "git", False, DAVE, consent.NOTICE_VERSION)
    assert await learned.usable(ORG, DAVE, "git") == []                              # a read checks consent too
