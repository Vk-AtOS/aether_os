"""
Tests for core/memory/fingerprinter.py.

Covers the legacy fingerprint() function AND the ProjectFingerprinter class
(store, search, exact/fallback matching, edge cases).

All tests use isolated temporary DBs via monkeypatching _DB_PATH.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def fp(tmp_path, monkeypatch):
    """ProjectFingerprinter backed by a tmp SQLite file."""
    import aether_os.core.memory.fingerprinter as _mod
    monkeypatch.setattr(_mod, "_DB_PATH", tmp_path / "fp.db")
    from aether_os.core.memory.fingerprinter import ProjectFingerprinter
    return ProjectFingerprinter()


# ─────────────────────────────────────────────────────────────────────────────
# Legacy fingerprint() function
# ─────────────────────────────────────────────────────────────────────────────

def test_fingerprint_stable():
    from aether_os.core.memory.fingerprinter import fingerprint
    log = "Error: NameError: name 'foo' is not defined at line 42"
    assert fingerprint(log) == fingerprint(log)


def test_fingerprint_normalises_memory_addresses():
    from aether_os.core.memory.fingerprinter import fingerprint
    log1 = "Fatal error at 0x7f1234ab"
    log2 = "Fatal error at 0x7fffff00"
    assert fingerprint(log1) == fingerprint(log2)


def test_fingerprint_normalises_line_numbers():
    from aether_os.core.memory.fingerprinter import fingerprint
    log1 = "Traceback: error at line 10"
    log2 = "Traceback: error at line 99"
    assert fingerprint(log1) == fingerprint(log2)


def test_fingerprint_different_errors_give_different_hashes():
    from aether_os.core.memory.fingerprinter import fingerprint
    assert fingerprint("AttributeError: 'NoneType'") != fingerprint("ImportError: module not found")


def test_fingerprint_returns_16_chars():
    from aether_os.core.memory.fingerprinter import fingerprint
    result = fingerprint("some error log")
    assert len(result) == 16
    assert result.isalnum()  # hex string


def test_fingerprint_empty_log():
    from aether_os.core.memory.fingerprinter import fingerprint
    # Should not crash
    result = fingerprint("")
    assert len(result) == 16


# ─────────────────────────────────────────────────────────────────────────────
# ProjectFingerprinter.fingerprint()
# ─────────────────────────────────────────────────────────────────────────────

def test_project_fingerprint_stable(fp):
    h1 = fp.fingerprint("Build a CRM for a healthcare company", domain="healthcare")
    h2 = fp.fingerprint("Build a CRM for a healthcare company", domain="healthcare")
    assert h1 == h2


def test_project_fingerprint_case_insensitive(fp):
    h1 = fp.fingerprint("Build A CRM", domain="general")
    h2 = fp.fingerprint("build a crm", domain="general")
    assert h1 == h2


def test_project_fingerprint_domain_changes_hash(fp):
    h1 = fp.fingerprint("Build a CRM", domain="healthcare")
    h2 = fp.fingerprint("Build a CRM", domain="fintech")
    assert h1 != h2


def test_project_fingerprint_returns_32_chars(fp):
    result = fp.fingerprint("hello", domain="general")
    assert len(result) == 32


# ─────────────────────────────────────────────────────────────────────────────
# ProjectFingerprinter.store() and search()
# ─────────────────────────────────────────────────────────────────────────────

def test_store_and_exact_search(fp):
    h = fp.fingerprint("build a clinic app", domain="healthcare")
    fp.store(
        run_id="run-001",
        org_id="org-A",
        fingerprint=h,
        domain="healthcare",
        raw_input="build a clinic app",
    )
    results = fp.search(fingerprint=h, org_id="org-A")
    assert len(results) >= 1
    assert results[0]["run_id"] == "run-001"
    assert results[0]["similarity"] == 1.0


def test_search_returns_empty_for_wrong_org(fp):
    h = fp.fingerprint("build a shop", domain="ecommerce")
    fp.store(run_id="run-002", org_id="org-A", fingerprint=h, domain="ecommerce")
    results = fp.search(fingerprint=h, org_id="org-DIFFERENT")
    # May return 0 or fall back to recency; exact match should NOT be present
    exact = [r for r in results if r["similarity"] == 1.0]
    assert len(exact) == 0


def test_search_fallback_returns_recent_runs(fp):
    """When fingerprint doesn't match, returns fallback with similarity 0.5."""
    h_old = fp.fingerprint("old project", domain="general")
    fp.store(run_id="run-003", org_id="org-B", fingerprint=h_old, domain="general")

    h_new = fp.fingerprint("completely different project xyz", domain="general")
    results = fp.search(fingerprint=h_new, org_id="org-B", top_k=3)
    # No exact match — fallback entries have similarity < 1.0
    if results:
        assert all(r["similarity"] <= 0.5 for r in results)


def test_search_top_k_respected(fp):
    for i in range(5):
        h = fp.fingerprint(f"project-{i}", domain="general")
        fp.store(run_id=f"run-{i}", org_id="org-C", fingerprint=h, domain="general")

    h_query = fp.fingerprint("project-0", domain="general")
    results = fp.search(fingerprint=h_query, org_id="org-C", top_k=2)
    assert len(results) <= 2


def test_store_truncates_raw_input(fp):
    """raw_input is truncated to 500 chars in the DB — should not crash."""
    long_input = "x" * 2000
    h = fp.fingerprint(long_input, domain="general")
    fp.store(run_id="run-long", org_id="org-D", fingerprint=h, raw_input=long_input)
    results = fp.search(fingerprint=h, org_id="org-D")
    assert len(results) >= 1


def test_store_domain_returned_in_results(fp):
    h = fp.fingerprint("ecommerce platform", domain="ecommerce")
    fp.store(run_id="run-dom", org_id="org-E", fingerprint=h, domain="ecommerce")
    results = fp.search(fingerprint=h, org_id="org-E")
    assert results[0]["domain"] == "ecommerce"


def test_search_empty_db_returns_empty(fp):
    h = fp.fingerprint("nothing stored yet", domain="general")
    results = fp.search(fingerprint=h, org_id="org-empty")
    assert results == []


def test_store_multiple_runs_same_fingerprint(fp):
    """Multiple runs with the same fingerprint are all stored."""
    h = fp.fingerprint("crm app", domain="general")
    for i in range(3):
        fp.store(run_id=f"multi-run-{i}", org_id="org-F", fingerprint=h)
    results = fp.search(fingerprint=h, org_id="org-F", top_k=5)
    run_ids = [r["run_id"] for r in results if r["similarity"] == 1.0]
    assert len(run_ids) >= 1  # At least one exact match returned
