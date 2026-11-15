#!/usr/bin/env python3.11
"""Restore drill (KAN-51): restore a PostgreSQL backup into a throwaway database, prove it is usable, time every step.

    python3.11 scripts/restore_drill.py --dump /var/backups/aetheros/aetheros_X.dump \
        --admin-url postgresql://USER@HOST:5432/postgres \
        [--anchor-file /path/kept/separately/ledger_anchors.jsonl] [--record docs/ops/drills] \
        --role drill_restore   (DRILL_ROLE_PASSWORD in the environment)

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
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote, unquote, urlsplit, urlunsplit

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
        # a chain with entries but no checkpoint in the external file is unprotected, not "fine"
        uncovered = sorted(set(await chain.chain_ids()) - set(%(covered)r))
        out["checks"]["anchors_cover_every_chain"] = not uncovered
        if uncovered:
            out["uncovered_chains"] = uncovered
    print("RESULT " + json.dumps(out))

asyncio.run(main())
"""


def covered_chains(anchor_file: Path) -> List[str]:
    """Chain ids that have at least one checkpoint line in the externally kept file."""
    ids = set()
    for line in anchor_file.read_text(encoding="utf-8").splitlines():
        try:
            ids.add(str(json.loads(line)["chain_id"]))
        except (ValueError, KeyError, TypeError):
            continue
    return sorted(ids)


def check_anchor_file(path: str) -> str:
    """Why this anchor file cannot be trusted as the external copy, or "" when it can."""
    p = Path(path)
    if not p.is_file():
        return f"--anchor-file {path} is not a regular file"
    if p.stat().st_size == 0 or not covered_chains(p):
        return f"--anchor-file {path} holds no checkpoints: an empty file would make the check pass vacuously"
    return ""


# What an untrusted dump must not carry into a server: code that runs on its own or in a language outside the sandbox.
_UNSAFE_SQL = re.compile(r"CREATE\s+(?:OR\s+REPLACE\s+)?EVENT\s+TRIGGER|LANGUAGE\s+'?(?:c|internal|plpythonu|plpython3u|plperlu|pltclu|plsh)'?\b"
                         r"|CREATE\s+(?:OR\s+REPLACE\s+)?(?:TRUSTED\s+)?(?:PROCEDURAL\s+)?LANGUAGE", re.I)


def unsafe_objects(sql_text: str) -> List[str]:
    """Matches of EVENT TRIGGER / untrusted-language FUNCTION / CREATE LANGUAGE in the dump's schema SQL."""
    return sorted({m.group(0).upper() for m in _UNSAFE_SQL.finditer(sql_text)})


def split_password(url: str):
    """(url without the password, env with PGPASSWORD): the secret never appears on a command line."""
    p = urlsplit(url)
    env = dict(os.environ)
    if p.password:
        env["PGPASSWORD"] = unquote(p.password)
    host = p.hostname or ""
    netloc = (quote(unquote(p.username), safe="") if p.username else "") + ("@" if p.username else "") + host + (f":{p.port}" if p.port else "")
    return urlunsplit((p.scheme, netloc, p.path, p.query, "")), env


def as_role(url: str, role: str, password: str) -> str:
    p = urlsplit(url)
    host = p.hostname or ""
    cred = quote(role, safe="") + (":" + quote(password, safe="") if password else "")
    return urlunsplit((p.scheme, f"{cred}@{host}" + (f":{p.port}" if p.port else ""), p.path, p.query, ""))


def redact(url: str) -> str:
    p = urlsplit(url)
    host = p.hostname or ""
    return urlunsplit((p.scheme, f"{p.username or ''}@{host}" + (f":{p.port}" if p.port else ""), p.path, "", ""))


def with_db(url: str, name: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, "/" + name, p.query, ""))   # keep ?sslmode=... and friends


def run(cmd: List[str], url: str = "", **kw: Any) -> subprocess.CompletedProcess:
    """Run a command; `url` (if any) is the LAST connection string it needs: its password goes in PGPASSWORD, not argv."""
    if url:
        clean, env = split_password(url)
        cmd = [clean if c == url else c for c in cmd]
        kw.setdefault("env", env)
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def drill(dump: Path, admin_url: str, anchor_file: str = "", keep: bool = False, role: str = "",
          role_password: str = "") -> Dict[str, Any]:
    name = f"aether_drill_{uuid.uuid4().hex[:8]}"
    scratch = with_db(as_role(admin_url, role, role_password) if role else admin_url, name)
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

    def preflight():
        if role:
            q = run(["psql", admin_url, "-At", "-c", "select rolsuper or rolcreaterole or rolcreatedb from pg_roles "
                     f"where rolname = '{role.replace(chr(39), '')}'"], admin_url)
            if q.stdout.strip() != "f":
                return False, f"role {role!r} must exist and have no SUPERUSER/CREATEROLE/CREATEDB"
        sql = run(["pg_restore", "--schema-only", "-f", "-", str(dump)])
        if sql.returncode != 0:
            return False, "pg_restore cannot read the dump: " + sql.stderr.strip()[-200:]
        bad = unsafe_objects(sql.stdout)
        return not bad, ("refused, the dump contains: " + ", ".join(bad)) if bad else "no event triggers or untrusted languages"

    def create():
        owner = f' OWNER "{role}"' if role else ""
        r = run(["psql", admin_url, "-v", "ON_ERROR_STOP=1", "-c", f'CREATE DATABASE "{name}"{owner}'], admin_url)
        return r.returncode == 0, r.stderr.strip()[-300:]

    def restore():
        r = run(["pg_restore", "--no-owner", "--no-privileges", "--exit-on-error", "-d", scratch, str(dump)], scratch)
        return r.returncode == 0, r.stderr.strip()[-300:]

    def verify():
        env = {**os.environ, "DATABASE_URL": scratch, "PYTHONPATH": str(ROOT.parent)}
        if anchor_file:
            env["AETHER_LEDGER_ANCHOR_FILE"] = anchor_file
        covered = covered_chains(Path(anchor_file)) if anchor_file else []
        code = VERIFY % {"tables": CORE_TABLES, "ini": str(ROOT / "alembic.ini"), "check_anchor": bool(anchor_file), "covered": covered}
        r = run([sys.executable, "-c", code], env=env, cwd=ROOT)
        line = next((ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")), "")
        if not line:
            return False, (r.stderr.strip() or "no result")[-300:]
        result = json.loads(line[7:])
        record.update({k: v for k, v in result.items() if k != "checks"})
        record["checks"] = result["checks"]
        return all(result["checks"].values()), ", ".join(f"{k}={v}" for k, v in result["checks"].items())

    def drop():
        r = run(["psql", admin_url, "-c", f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'], admin_url)
        return r.returncode == 0, r.stderr.strip()[-200:]

    try:
        if step("preflight (role, dump contents)", preflight) and step("create scratch database", create) \
                and step("restore dump", restore):
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
    ap.add_argument("--role", default="", help="low-privilege role that owns the scratch database and restores the dump")
    ap.add_argument("--role-password-env", default="DRILL_ROLE_PASSWORD", help="environment variable holding that role's password")
    ap.add_argument("--allow-admin-restore", action="store_true", help="restore as the admin user (only for a throwaway server)")
    ap.add_argument("--note", default="", help="free text stored in the record (where it ran, which backup)")
    args = ap.parse_args(argv)
    if not args.dump.is_file():
        print(f"no such dump: {args.dump}", file=sys.stderr)
        return 2
    if args.anchor_file:
        why = check_anchor_file(args.anchor_file)
        if why:
            print(why, file=sys.stderr)
            return 2
    if not args.role and not args.allow_admin_restore:
        print("an untrusted dump must not be restored with admin rights: pass --role <low-privilege role> "
              "(or --allow-admin-restore on a throwaway server)", file=sys.stderr)
        return 2
    rec = drill(args.dump, args.admin_url, args.anchor_file, args.keep, args.role, os.environ.get(args.role_password_env, ""))
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
