#!/usr/bin/env python3
"""KAN-266: the multi-prompt acceptance suite. Builds six different request types and checks the BEHAVIOUR of each app.

    # local server (scripts/local.sh up), token from `scripts/local.sh`'s test account
    python3 scripts/acceptance_suite.py --base-url http://127.0.0.1:8000 --email local-e2e@aetheros.test --password ...
    # prod: base URL + a token (never write it to a file)
    ACCEPT_TOKEN=... python3 scripts/acceptance_suite.py --base-url https://<host> --only task_tracker,bakery_site

Expectations live in scripts/acceptance/prompts.json (see docs/ACCEPTANCE.md). Builds start with mode="autonomous";
a gate that waits for a human is reported as such, never approved. Writes <out>/suite-<UTC>.json and .md.
Exit 0 only when every selected prompt passed every check (--strict: skipped checks count as failures).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from acceptance import suite_checks as C  # noqa: E402
from acceptance import suite_export as X  # noqa: E402
from acceptance import suite_http as H  # noqa: E402
from acceptance import suite_report as R  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EXPECTATIONS = Path(__file__).resolve().parent / "acceptance" / "prompts.json"
FINAL = {"completed", "failed", "cancelled", "error", "timeout"}
KNOWN_KEYS = {"id", "title", "prompt", "run_status", "allow_skipped_stages", "app_started", "root_page", "frontend_build", "export_clean",
              "rulepacks_zero_blocking", "export_forbidden_patterns", "public_endpoints", "protected_endpoints", "form_post",
              "auth_crud", "chat", "no_accounts"}
ENDPOINT_KEYS = {"public_endpoints", "protected_endpoints"}


def load_expectations(path: Path = EXPECTATIONS) -> Tuple[dict, List[dict]]:
    data = json.loads(path.read_text())
    return data["defaults"], data["prompts"]


def validate_expectations(defaults: dict, prompts: List[dict]) -> List[str]:
    """Problems with the expectation data (empty = valid). Run offline by the unit test."""
    import re
    errs: List[str] = []
    ids = [p.get("id") for p in prompts]
    if len(set(ids)) != len(ids):
        errs.append("duplicate prompt ids")
    for k in defaults:
        if k not in KNOWN_KEYS:
            errs.append(f"defaults: unknown key {k}")
    for p in prompts:
        pid = p.get("id", "?")
        if len(str(p.get("prompt", ""))) < 80:
            errs.append(f"{pid}: prompt missing or too short to be realistic")
        errs += [f"{pid}: unknown key {k}" for k in p if k not in KNOWN_KEYS]
        items = [it for k in ENDPOINT_KEYS for it in p.get(k, [])]
        items += [p[k] for k in ("form_post", "auth_crud", "chat") if k in p]
        for it in items:
            for field in ("name", "path_regex"):
                if not it.get(field):
                    errs.append(f"{pid}: endpoint expectation without {field}: {it}")
            try:
                re.compile(it.get("path_regex", ""))
            except re.error as e:
                errs.append(f"{pid}: bad path_regex {it.get('path_regex')!r}: {e}")
        for rx in p.get("export_forbidden_patterns", []):
            try:
                re.compile(rx)
            except re.error as e:
                errs.append(f"{pid}: bad forbidden pattern {rx!r}: {e}")
        if "no_accounts" in p and any(k in p for k in ("auth_crud", "protected_endpoints")) and p.get("protected_endpoints"):
            errs.append(f"{pid}: a no-accounts prompt cannot expect protected endpoints")
    return errs


def poll_run(api, run_id: str, deadline: float, interval: float, sleep: Callable[[float], None]) -> Tuple[dict, str]:
    """Poll GET /factory/runs/{id} to a final status. (run record, why-not-final). Never approves a gate."""
    run: dict = {}
    while True:     # always poll once, even when the deadline is already past
        r = api.request("GET", f"/factory/runs/{run_id}")
        if r.status == 200 and isinstance(r.body, dict):
            run = r.body
            if str(run.get("status", "")).lower() in FINAL:
                return run, ""
        if time.time() >= deadline:
            break
        sleep(interval)
    st = str(run.get("status", "")).lower() or "unknown"
    waiting = st.startswith(("await", "wait", "paused", "pending_approval"))
    return run, (f"stuck at status {st!r} waiting for a human gate (the suite never approves one)" if waiting
                 else f"timed out while status was {st!r}, current stage {run.get('current_phase')}")


def run_prompt(api, entry: dict, defaults: dict, *, max_minutes: float = 45, interval: float = 15, sleep=time.sleep,
               build_frontend: bool = False, probe_mode: str = "preview", strict: bool = False) -> dict:
    exp = {**defaults, **entry}
    t0, run_id = time.time(), ""
    checks: List[C.CheckResult] = []

    def blocked(why: str) -> None:
        names = ["run_status", "all_stages_passed", "app_started", "export_clean", "frontend_build_tsc"]
        checks.extend(C.skip(n, f"not reached: {why}") for n in names if not any(c.name == n for c in checks))

    start = api.request("POST", "/factory/start", json={"raw_input": exp["prompt"], "domain": "general", "mode": "autonomous",
                                                        "project_name": f"acceptance-{exp['id']}-{int(t0) % 100000}"})
    run_id = (start.body or {}).get("run_id", "") if isinstance(start.body, dict) else ""
    if start.status != 200 or not run_id:
        checks.append(C.fail("run_status", f"POST /factory/start answered {start.status}: {start.text[:200]}"))
        blocked("the build never started")
        return R.prompt_record(entry, run_id, time.time() - t0, checks, strict)

    run, why = poll_run(api, run_id, t0 + max_minutes * 60, interval, sleep)
    checks.append(C.check_run_status(run, exp["run_status"]) if not why else C.fail("run_status", why))
    checks.append(C.check_stages(run, exp["allow_skipped_stages"]))
    status = api.request("GET", f"/factory/runs/{run_id}/run-app/status")
    checks.append(C.check_app_started(status) if exp["app_started"] else C.skip("app_started", "not expected for this prompt"))

    dl_status, zip_bytes, dl_text = api.get_bytes(f"/factory/runs/{run_id}/download")
    local: Optional[dict] = None
    if dl_status != 200 or not zip_bytes:
        why = f"download answered {dl_status}: {dl_text[:240]}"
        wanted = [("export_clean", "export_clean"), ("rulepacks_zero_blocking", "rulepacks_zero_blocking"),
                  ("frontend_build", "frontend_build_tsc")]
        checks.extend(C.fail(name, why) for key, name in wanted if exp[key])
    else:
        if exp["export_clean"]:
            checks.append(X.check_export_clean(zip_bytes))
        if exp["export_forbidden_patterns"]:
            checks.append(X.check_forbidden_patterns(zip_bytes, exp["export_forbidden_patterns"]))
        if exp["rulepacks_zero_blocking"]:
            checks.append(X.check_rulepacks(zip_bytes))
        if exp["frontend_build"]:
            local = X.local_frontend_build(zip_bytes) if build_frontend else None
            checks.append(C.check_frontend_build(run, local))

    # Behaviour of the running app
    app_checks = any(k in exp for k in ("public_endpoints", "protected_endpoints", "form_post", "auth_crud", "chat", "no_accounts")) or exp["root_page"]
    local_app = None
    if app_checks:
        probe, perr = (None, "")
        if probe_mode == "local" and zip_bytes:
            local_app = H.LocalApp(zip_bytes)
            probe, perr = local_app.start()
        elif probe_mode == "preview":
            probe, perr = H.preview_probe(api, run_id)
        try:
            checks.extend(_behaviour(api, probe, perr, run_id, exp))
        finally:
            if local_app:
                local_app.stop()
    return R.prompt_record(entry, run_id, time.time() - t0, checks, strict)


def _behaviour(api, probe, perr: str, run_id: str, exp: dict) -> List[C.CheckResult]:
    if probe is None:
        why = f"could not reach the running app: {perr}"
        names = ["root_page"] + [f"{k}" for k in ("public_endpoints", "protected_endpoints", "form_post", "auth_crud", "chat", "no_accounts") if k in exp]
        return [C.fail(n, why) for n in names]
    out: List[C.CheckResult] = []
    spec, why_spec = C.load_openapi(probe)
    if exp["root_page"]:
        out.append(C.check_root_page(probe))
    if spec is None and "no_accounts" not in exp:
        out.append(C.fail("openapi", why_spec))
    out += C.check_public(probe, spec, exp.get("public_endpoints", []))
    out += C.check_protected(probe, spec, exp.get("protected_endpoints", []))
    if "form_post" in exp:
        out.append(C.check_form_post(probe, spec, exp["form_post"]))
    if "chat" in exp:
        out.append(C.check_chat(probe, spec, exp["chat"]))
    if "no_accounts" in exp:
        out.append(C.check_no_accounts(spec, exp["no_accounts"]))
    if "auth_crud" in exp:
        creds = api.request("GET", f"/factory/runs/{run_id}/preview-credentials")
        token, why = _login(probe, spec, creds)
        out.append(C.check_auth_crud(probe, spec, exp["auth_crud"], token, why))
    return out


def _login(probe, spec, creds: C.Resp) -> Tuple[str, str]:
    if creds.status != 200 or not isinstance(creds.body, dict):
        return "", f"preview-credentials answered {creds.status}: {creds.text[:160]}"
    return C.app_login(probe, spec, creds.body)


def run_suite(api, defaults: dict, entries: List[dict], concurrency: int = 1, **kw) -> List[dict]:
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        return list(pool.map(lambda e: run_prompt(api, e, defaults, **kw), entries))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=os.environ.get("ACCEPT_API", "http://127.0.0.1:8000"))
    ap.add_argument("--email", default=os.environ.get("ACCEPT_EMAIL", ""))
    ap.add_argument("--password", default=os.environ.get("ACCEPT_PASSWORD", ""), help="or env ACCEPT_PASSWORD")
    ap.add_argument("--only", default="", help="comma-separated prompt ids")
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--max-minutes", type=float, default=45)
    ap.add_argument("--probe", choices=("preview", "local"), default="preview",
                    help="preview: probe the platform's preview origin; local: start the exported backend here (needs pip + network)")
    ap.add_argument("--build-frontend", action="store_true", help="npm install + tsc + vite build on the exported frontend")
    ap.add_argument("--strict", action="store_true", help="a SKIPPED check fails the prompt")
    ap.add_argument("--validate-only", action="store_true", help="check the expectation file and exit")
    ap.add_argument("--out", default=str(ROOT / "docs/acceptance"))
    args = ap.parse_args(argv)
    defaults, prompts = load_expectations()
    errs = validate_expectations(defaults, prompts)
    if errs:
        print("expectation file invalid:\n  " + "\n  ".join(errs))
        return 2
    if args.validate_only:
        print(f"ok: {len(prompts)} prompts")
        return 0
    wanted = {s for s in args.only.split(",") if s}
    entries = [p for p in prompts if not wanted or p["id"] in wanted]
    if wanted - {p["id"] for p in prompts} or not entries:
        print("unknown prompt id(s):", sorted(wanted - {p['id'] for p in prompts}))
        return 2
    token = os.environ.get("ACCEPT_TOKEN", "")
    if not token and args.email:
        token, why = H.login(args.base_url, args.email, args.password)
        if not token:
            print("SKIP: " + why)
            return 2
    if not token:
        print("SKIP: no ACCEPT_TOKEN and no --email/--password; nothing was run")
        return 2
    api = H.Probe(args.base_url, token)
    if api.request("GET", "/health", timeout=10).status != 200:
        print(f"SKIP: {args.base_url}/health did not answer 200; nothing was run")
        return 2
    records = run_suite(api, defaults, entries, args.concurrency, max_minutes=args.max_minutes,
                        build_frontend=args.build_frontend, probe_mode=args.probe, strict=args.strict)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    report = R.summary(records, {"at": stamp, "target": args.base_url, "probe": args.probe, "strict": args.strict})
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"suite-{stamp}.json").write_text(R.to_json(report))
    (out / f"suite-{stamp}.md").write_text(R.to_markdown(report))
    print(R.to_markdown(report))
    return R.exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
