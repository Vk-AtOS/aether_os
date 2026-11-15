#!/usr/bin/env python3.11
"""Restore drill (KAN-51): restore a PostgreSQL backup into a throwaway database, prove it is usable, time every step.

    python3.11 scripts/restore_drill.py --dump /var/backups/aetheros/aetheros_X.dump \
        --admin-url postgresql://USER@HOST:5432/postgres \
        [--anchor-file /path/kept/separately/ledger_anchors.jsonl] [--record docs/ops/drills]

The dump must be `pg_dump --format=custom` (deploy/scripts/backup.sh). The admin URL needs CREATEDB on a server that is NOT
production: the drill creates `aether_drill_<id>`, restores into it, checks, and drops it (--keep leaves it for inspection).
Checks: the schema is at this code's Alembic head; core tables exist and are not empty; every audit chain verifies end to end;
with --anchor-file, the restored chains also match the signed checkpoints kept OUTSIDE the database (a restore from a
tampered or rolled-back backup fails here). A JSON record with per-step seconds (the measured RTO) is written to --record.
Exit 0 = every check passed. Passwords are never written to the record.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
CORE_TABLES = ("organisations", "users", "runs", "audit_chain")

# Runs inside a child process whose DATABASE_URL is the restored database (the app reads it once, at import).
VERIFY = r"""
import asyncio, json
from sqlalchemy import text
from alembic.config import Config
from alembic.script import ScriptDirectory
from aether_os.core.db import get_session_factory
from aether_os.core.audit import anchor, chain

async def main():
    out = {"checks": {}}
    async with get_session_factory()() as s:
        have = {r[0] for r in (await s.execute(text("select version_num from alembic_version"))).all()}
        counts = {}
        for t in %(tables)r:
            counts[t] = (await s.execute(text(f"select count(*) from {t}"))).scalar_one()
    heads = set(ScriptDirectory.from_config(Config(%(ini)r)).get_heads())
    out["checks"]["schema_at_head"] = have == heads
    out["row_counts"] = counts
    out["checks"]["core_tables_present"] = True
    full = await chain.verify()
    out["checks"]["chains_verify"] = bool(full.ok)
    out["chain_entries"] = full.entries_checked
    if not full.ok:
        out["chain_failure"] = full.reason
    if %(check_anchor)r:
        problems = await anchor.check_file()
        out["checks"]["matches_external_anchors"] = not problems
        if problems:
            out["anchor_problems"] = problems
    print("RESULT " + json.dumps(out))

asyncio.run(main())
"""


def redact(url: str) -> str:
    p = urlsplit(url)
    host = p.hostname or ""
    return urlunsplit((p.scheme, f"{p.username or ''}@{host}" + (f":{p.port}" if p.port else ""), p.path, "", ""))


def with_db(url: str, name: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, "/" + name, "", ""))


def run(cmd: List[str], **kw: Any) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def drill(dump: Path, admin_url: str, anchor_file: str = "", keep: bool = False) -> Dict[str, Any]:
    name = f"aether_drill_{uuid.uuid4().hex[:8]}"
    scratch = with_db(admin_url, name)
    steps: List[Dict[str, Any]] = []
    record: Dict[str, Any] = {"dump": dump.name, "dump_bytes": dump.stat().st_size, "server": redact(admin_url),
                              "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "steps": steps,
                              "passed": False}
    t_all = time.monotonic()

    def step(label: str, fn):
        t0 = time.monotonic()
        ok, detail = fn()
        steps.append({"step": label, "seconds": round(time.monotonic() - t0, 2), "ok": ok, "detail": detail})
        return ok

    def create():
        r = run(["psql", admin_url, "-v", "ON_ERROR_STOP=1", "-c", f'CREATE DATABASE "{name}"'])
        return r.returncode == 0, r.stderr.strip()[-300:]

    def restore():
        r = run(["pg_restore", "--no-owner", "--no-privileges", "--exit-on-error", "-d", scratch, str(dump)])
        return r.returncode == 0, r.stderr.strip()[-300:]

    def verify():
        env = {**os.environ, "DATABASE_URL": scratch, "PYTHONPATH": str(ROOT.parent)}
        if anchor_file:
            env["AETHER_LEDGER_ANCHOR_FILE"] = anchor_file
        code = VERIFY % {"tables": CORE_TABLES, "ini": str(ROOT / "alembic.ini"), "check_anchor": bool(anchor_file)}
        r = run([sys.executable, "-c", code], env=env, cwd=ROOT)
        line = next((ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")), "")
        if not line:
            return False, (r.stderr.strip() or "no result")[-300:]
        result = json.loads(line[7:])
        record.update({k: v for k, v in result.items() if k != "checks"})
        record["checks"] = result["checks"]
        return all(result["checks"].values()), ", ".join(f"{k}={v}" for k, v in result["checks"].items())

    def drop():
        r = run(["psql", admin_url, "-c", f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'])
        return r.returncode == 0, r.stderr.strip()[-200:]

    try:
        if step("create scratch database", create) and step("restore dump", restore):
            step("verify restored data", verify)
    finally:
        if not keep:
            step("drop scratch database", drop)
    record["total_seconds"] = round(time.monotonic() - t_all, 2)
    record["passed"] = all(s["ok"] for s in steps) and bool(record.get("checks"))
    return record


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", required=True, type=Path)
    ap.add_argument("--admin-url", required=True)
    ap.add_argument("--anchor-file", default="")
    ap.add_argument("--record", type=Path, default=ROOT / "docs/ops/drills")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--note", default="", help="free text stored in the record (where it ran, which backup)")
    args = ap.parse_args(argv)
    if not args.dump.is_file():
        print(f"no such dump: {args.dump}", file=sys.stderr)
        return 2
    rec = drill(args.dump, args.admin_url, args.anchor_file, args.keep)
    rec["note"] = args.note
    args.record.mkdir(parents=True, exist_ok=True)
    out = args.record / f"restore-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    out.write_text(json.dumps(rec, indent=2) + "\n")
    for s in rec["steps"]:
        print(f"{'ok  ' if s['ok'] else 'FAIL'} {s['seconds']:>7.2f}s  {s['step']}  {s['detail']}")
    print(f"{'PASS' if rec['passed'] else 'FAIL'}: restored and verified in {rec['total_seconds']}s -> {out}")
    return 0 if rec["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
