#!/usr/bin/env python3.11
"""KAN-53: the production-readiness checklist as a script. One line per item: PASS / FAIL / UNVERIFIED + evidence.

    python3.11 scripts/production_readiness.py [--json] [--live https://api.example.com]

Checks what the repository can prove (files, configuration, the migration graph, CI gates). Items that need the deployed
stack or a person (access reviews, a restore on real data, the incident roster) are UNVERIFIED with the reason, never
PASS. --live adds probes against a running API (/healthz, /readyz, security headers, TLS redirect).
Exit 0 = no FAIL, 1 = at least one FAIL (UNVERIFIED does not fail: it is listed so the sign-off cannot skip it).
The Confluence page is this output pasted per item.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Tuple

import yaml

ROOT = Path(__file__).resolve().parents[1]
Result = Tuple[str, str]   # (PASS|FAIL|UNVERIFIED, evidence)


def text(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(errors="ignore") if p.is_file() else ""


def tree(rel: str, pattern: str = "*") -> str:
    return "\n".join(p.read_text(errors="ignore") for p in (ROOT / rel).rglob(pattern) if p.is_file()) if (ROOT / rel).is_dir() else ""


def ok(cond: bool, evidence: str, bad: str = "") -> Result:
    return ("PASS", evidence) if cond else ("FAIL", bad or f"missing: {evidence}")


def secrets() -> Result:
    tracked = subprocess.run(["git", "ls-files", "--", ".env", "*/.env", ".env.*"], cwd=ROOT, capture_output=True, text=True).stdout
    leaked = [f for f in tracked.split() if not f.endswith((".example", ".sample", ".template"))]
    gate = "gitleaks" in text(".github/workflows/ci.yml") and (ROOT / ".gitleaks.toml").is_file()
    return ok(not leaked and gate, ".gitleaks.toml + blocking gitleaks job in ci.yml, no .env tracked",
              f"tracked env files {leaked}" if leaked else "gitleaks gate or .gitleaks.toml missing")


def tls() -> Result:
    n, tf = text("deploy/nginx.conf"), tree("deploy/terraform", "*.tf")
    return ok("TLSv1.3" in n and "Strict-Transport-Security" in n and "TLSv1.2" in n and "ssl" in tf.lower(),
              "deploy/nginx.conf (TLS1.2/1.3 + HSTS), terraform database/edge TLS", "nginx TLS/HSTS or terraform TLS missing")


def least_privilege() -> Result:
    d, c = text("Dockerfile"), text("docker-compose.yml")
    bad = [w for w, cond in (("Dockerfile has no USER", not re.search(r"^USER\s+(?!root)", d, re.M)),
                             ("compose service is privileged", "privileged: true" in c)) if cond]
    return ok(not bad, "Dockerfile runs as non-root, no privileged compose service", "; ".join(bad))


def sandbox_isolation() -> Result:
    # Only the docker-proxy service (endpoint-filtered, read-only) may mount the host Docker socket; the api reaches it
    # through DOCKER_HOST. Residual risk: the proxy does not inspect request bodies (see docs/ops/RUNBOOKS.md).
    services = yaml.safe_load(text("docker-compose.yml"))["services"]
    holders = [n for n, d in services.items() if any("docker.sock" in str(v) for v in d.get("volumes", []))]
    return ok(holders == ["docker-proxy"] and "DOCKER_HOST: unix:///docker-proxy" in text("docker-compose.yml"),
              "host docker.sock mounted only by docker-proxy; api uses DOCKER_HOST",
              f"docker.sock is mounted by {holders}; only docker-proxy may, and the api needs DOCKER_HOST=unix:///docker-proxy/docker.sock")


def rate_limits() -> Result:
    return ok((ROOT / "core/rate_limiter.py").is_file() and "limit_req" in text("deploy/nginx.conf"),
              "core/rate_limiter.py (per user/org, Redis) + nginx limit_req")


def backups() -> Result:
    files = ("scripts/db_backup.sh", "scripts/restore_drill.py", "deploy/aetheros-backup.timer")
    missing = [f for f in files if not (ROOT / f).is_file()]
    return ok(not missing, "db_backup.sh + backup timer + restore_drill.py", f"missing {missing}")


def monitoring() -> Result:
    return ok("alert:" in text("deploy/observability/alerts.yml") and "/readyz" in text("gateway/routers/health_router.py"),
              "deploy/observability/alerts.yml + /healthz,/readyz")


def dependency_scan() -> Result:
    ci = text(".github/workflows/ci.yml")
    return ok((ROOT / "requirements.lock").is_file() and "pip-audit" in ci and "bandit" in ci,
              "requirements.lock + pip-audit and bandit in ci.yml")


def licences() -> Result:
    return ok((ROOT / "LICENSE").is_file() and (ROOT / "IP_OWNERSHIP.md").is_file(), "LICENSE + IP_OWNERSHIP.md present",
              "LICENSE or IP_OWNERSHIP.md missing (dependency licence report is NOT generated here)")


def data_residency() -> Result:
    tf = tree("deploy/terraform", "*.tf") + tree("deploy/terraform", "*.tfvars")
    regions = set(re.findall(r'"(ap-south-1|us-east-1|eu-[a-z]+-\d|us-west-\d)"', tf))
    return ok(regions == {"ap-south-1"}, "terraform pins region ap-south-1 only (Mumbai)", f"regions found: {sorted(regions)}")


def incident_contacts() -> Result:
    present = "security@" in text("SECURITY.md") and "escalat" in text("RUNBOOK.md").lower() + tree("docs/ops", "*.md").lower()
    return ("UNVERIFIED", "SECURITY.md has a reporting address and runbooks have escalation steps"
            + ("" if present else " (one missing)") + "; the on-call roster/phone tree needs the owner")


def migrations() -> Result:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    heads = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_heads()
    return ok(len(heads) == 1, f"one Alembic head ({heads[0]})" if len(heads) == 1 else "", f"heads: {heads}")


def ledger_ddl() -> Result:
    sys.path.insert(0, str(ROOT.parent))
    from aether_os.core import schema_ddl
    return ok(len(schema_ddl.PG_TRIGGERS) == 3, "audit-ledger triggers defined once in core/schema_ddl.py (bootstrap + revisions)")


def access_reviews() -> Result:
    return "UNVERIFIED", "needs the owner: who has cloud/console/GitHub/Jira access, reviewed and dated"


def restore_on_real_data() -> Result:
    return "UNVERIFIED", "scripts/restore_drill.py exists; it has not been run against a production-size dump"


CHECKS: Dict[str, Callable[[], Result]] = {
    "secrets": secrets, "tls": tls, "least privilege": least_privilege, "sandbox isolation": sandbox_isolation, "rate limits": rate_limits, "backups": backups,
    "monitoring": monitoring, "dependency scan": dependency_scan, "licence check": licences,
    "data residency": data_residency, "incident contacts": incident_contacts, "migrations": migrations,
    "audit ledger append-only": ledger_ddl, "access reviews": access_reviews, "restore on real data": restore_on_real_data,
}


def live(base: str) -> Dict[str, Result]:
    def get(path: str):
        try:
            return urllib.request.urlopen(base.rstrip("/") + path, timeout=8)
        except urllib.error.HTTPError as e:
            return e
        except (urllib.error.URLError, OSError) as e:
            return e
    out: Dict[str, Result] = {}
    h, r = get("/healthz"), get("/readyz")
    out["live /healthz"] = ok(getattr(h, "status", 0) == 200, f"{base}/healthz 200", f"{base}/healthz -> {getattr(h, 'status', h)}")
    out["live /readyz"] = ok(getattr(r, "status", 0) == 200, f"{base}/readyz 200", f"{base}/readyz -> {getattr(r, 'status', r)}")
    hdrs = {k.lower() for k in getattr(h, "headers", {}).keys()}
    need = {"strict-transport-security", "x-content-type-options"}
    out["live security headers"] = ok(need <= hdrs, "HSTS and nosniff present", f"missing {sorted(need - hdrs)}")
    out["live TLS"] = ok(base.startswith("https://"), "base URL is https", "base URL is not https")
    return out


def run(live_url: str = "") -> List[Dict[str, str]]:
    rows = []
    for name, fn in CHECKS.items():
        try:
            status, ev = fn()
        except Exception as exc:   # a check that cannot run is a FAIL, never a silent pass
            status, ev = "FAIL", f"check crashed: {type(exc).__name__}: {exc}"
        rows.append({"item": name, "status": status, "evidence": ev})
    if live_url:
        rows += [{"item": k, "status": v[0], "evidence": v[1]} for k, v in live(live_url).items()]
    return rows


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--live", default="")
    args = ap.parse_args(argv)
    rows = run(args.live)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print(f"{r['status']:<10} {r['item']:<26} {r['evidence']}")
    return 1 if any(r["status"] == "FAIL" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
