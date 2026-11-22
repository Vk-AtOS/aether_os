"""A patch that fixes a syntax error is kept even when tsc then reports type errors it could not reach before
(production acceptance run 16, 22 Nov 2026: the closing-tag fix was rolled back and s04 failed)."""
from __future__ import annotations

import asyncio
import subprocess

from aether_os.phases.p05_frontend import build_loop as bl

SYNTAX = "src/pages/Dashboard.tsx(84,56): error TS17002: Expected corresponding JSX closing tag for 'div'."
TYPES = ["src/a.tsx(1,1): error TS2345: x", "src/b.tsx(2,2): error TS2322: y", "src/c.tsx(3,3): error TS18046: z"]


def _after(monkeypatch, lines, code=1):
    async def fake_run(*a, **k):
        return subprocess.CompletedProcess(args=a, returncode=code, stdout="\n".join(lines), stderr="")
    monkeypatch.setattr(bl.phase_exec, "run", fake_run)


def test_fixing_the_syntax_error_wins_over_more_type_errors(monkeypatch, tmp_path):
    _after(monkeypatch, TYPES)
    assert asyncio.run(bl._tsc_not_worse(tmp_path, [SYNTAX]))


def test_a_new_syntax_error_is_rolled_back(monkeypatch, tmp_path):
    _after(monkeypatch, [SYNTAX, SYNTAX.replace("84,56", "90,1")])
    assert not asyncio.run(bl._tsc_not_worse(tmp_path, [SYNTAX]))


def test_without_syntax_errors_the_total_decides(monkeypatch, tmp_path):
    _after(monkeypatch, TYPES)
    assert not asyncio.run(bl._tsc_not_worse(tmp_path, TYPES[:2]))
    assert asyncio.run(bl._tsc_not_worse(tmp_path, TYPES))


def test_clean_tsc_is_always_accepted(monkeypatch, tmp_path):
    _after(monkeypatch, [], code=0)
    assert asyncio.run(bl._tsc_not_worse(tmp_path, [SYNTAX]))


def test_ts18xxx_is_not_a_syntax_error():
    assert bl._syntax_errors([SYNTAX, "x(1,1): error TS1005: ';' expected.", TYPES[2]]) == 2
