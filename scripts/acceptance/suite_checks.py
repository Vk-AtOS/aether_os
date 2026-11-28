"""KAN-266: behaviour checks of one generated app. Pure functions over a Probe (an HTTP-like object), so tests use fakes.

Endpoint names are model-generated, so a check never hard-codes a path: it matches a regex against the generated app's
own OpenAPI document. A check that cannot find what it needs FAILS with the reason (it never silently passes).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
METHODS = ("get", "post", "put", "patch", "delete")


@dataclass
class Resp:
    status: int            # 0 = no HTTP answer (connection error); text then holds the error
    body: Any = None       # parsed JSON, or None
    text: str = ""


@dataclass
class CheckResult:
    name: str
    status: str
    reason: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)


def ok(name: str, reason: str = "", **detail: Any) -> CheckResult:
    return CheckResult(name, PASS, reason, detail)


def fail(name: str, reason: str, **detail: Any) -> CheckResult:
    return CheckResult(name, FAIL, reason, detail)


def skip(name: str, reason: str) -> CheckResult:
    return CheckResult(name, SKIP, reason)


# ---- OpenAPI helpers --------------------------------------------------------------------------------------------

def load_openapi(probe) -> Tuple[Optional[dict], str]:
    """The generated app's OpenAPI document, trying the usual mount points. (doc, reason-if-none)."""
    tried = []
    for p in ("/openapi.json", "/api/openapi.json", "/api/v1/openapi.json"):
        r = probe.request("GET", p)
        if r.status == 200 and isinstance(r.body, dict) and "paths" in r.body:
            return r.body, ""
        tried.append(f"{p} -> {r.status or r.text[:60]}")
    return None, "no OpenAPI document: " + "; ".join(tried)


def find_ops(spec: dict, regex: str, method: str, with_params: bool = False) -> List[str]:
    """Paths whose name matches `regex` and that offer `method`; collection paths (no {param}) first, shortest first."""
    rx = re.compile(regex, re.I)
    paths = [p for p, ops in (spec.get("paths") or {}).items()
             if rx.search(p) and method.lower() in ops and (with_params or "{" not in p)]
    return sorted(paths, key=lambda p: (len(p), p))


def _resolve(schema: Any, spec: dict, depth: int = 0) -> dict:
    if not isinstance(schema, dict) or depth > 8:
        return {}
    if "$ref" in schema:
        node: Any = spec
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node.get(part, {}) if isinstance(node, dict) else {}
        return _resolve(node, spec, depth + 1)
    for key in ("anyOf", "oneOf", "allOf"):
        if schema.get(key):
            opts = [o for o in schema[key] if o.get("type") != "null"] or schema[key]
            return _resolve(opts[0], spec, depth + 1)
    return schema


def make_value(schema: Any, spec: dict, name: str = "", depth: int = 0) -> Any:
    """A schema-valid sample value (required fields only for objects), so a POST fails for real reasons, not 422."""
    s = _resolve(schema, spec)
    if "enum" in s:
        return s["enum"][0]
    t, fmt, lname = s.get("type"), s.get("format", ""), name.lower()
    if t == "string":
        if fmt == "email" or "email" in lname:
            return "acceptance@example.com"
        if fmt in ("date-time", "datetime"):
            return "2030-01-01T10:00:00"
        if fmt == "date" or lname.endswith("date"):
            return "2030-01-01"
        if fmt == "time":
            return "10:00:00"
        if "phone" in lname:
            return "+15550100"
        if "password" in lname:
            return "Acceptance-Check-2030!"
        return "Acceptance check"
    if t == "integer":
        return max(int(s.get("minimum", 1)), 1)
    if t == "number":
        return max(float(s.get("minimum", 1.0)), 1.0)
    if t == "boolean":
        return True
    if t == "array":
        return [make_value(s.get("items", {}), spec, name, depth + 1)] if depth < 4 else []
    if t == "object" or "properties" in s:
        props, req = s.get("properties", {}), s.get("required", [])
        return {k: make_value(v, spec, k, depth + 1) for k, v in props.items() if k in req}
    return "Acceptance check"


def body_for(spec: dict, path: str, method: str, overrides: Optional[dict] = None) -> Any:
    op = (spec.get("paths", {}).get(path, {}) or {}).get(method.lower(), {})
    content = ((op.get("requestBody") or {}).get("content") or {})
    schema = (content.get("application/json") or next(iter(content.values()), {})).get("schema", {})
    body = make_value(schema, spec)
    if isinstance(body, dict):
        body.update(overrides or {})
    return body


def _fill_params(path: str, value: str = "1") -> str:
    return re.sub(r"\{[^}]+\}", value, path)


# ---- run-level checks (from the platform's run record) ---------------------------------------------------------

def check_run_status(run: dict, want: str) -> CheckResult:
    got = str(run.get("status", "")).lower()
    if got == want:
        return ok("run_status", got)
    return fail("run_status", f"run ended {got or 'with no status'}, wanted {want}: {run.get('error') or run.get('failure_reason') or 'no error recorded'}")


def check_stages(run: dict, allow_skipped: List[str]) -> CheckResult:
    """Every stage passed. A skipped stage counts as not passed unless the prompt lists it as legitimately skippable."""
    failed = list(run.get("failed_stages") or [])
    skipped = [s for s in (run.get("skipped_stages") or []) if (s.get("stage") if isinstance(s, dict) else s) not in allow_skipped]
    if not failed and "failed_stages" not in run:       # an older server: fall back to the raw per-stage statuses
        for name, ph in (run.get("phases") or {}).items():
            st = str((ph or {}).get("status", "")).lower()
            if st in ("failed", "timeout", "escalated", "error"):
                failed.append({"stage": name, "status": st, "reason": "see run record"})
    if failed or skipped:
        why = [f"{f.get('stage')}: {f.get('status')} ({str(f.get('reason'))[:160]})" for f in failed]
        why += [f"{(s.get('stage') if isinstance(s, dict) else s)}: skipped ({(s.get('reason') if isinstance(s, dict) else '')})" for s in skipped]
        return fail("all_stages_passed", "; ".join(why), failed=len(failed), skipped=len(skipped))
    return ok("all_stages_passed", f"{len(run.get('phases') or {})} stages, none failed or skipped")


def check_app_started(status: Resp) -> CheckResult:
    if status.status != 200 or not isinstance(status.body, dict):
        return fail("app_started", f"run-app/status answered {status.status}: {status.text[:120]}")
    if status.body.get("running") is True:
        return ok("app_started", f"running on port {status.body.get('port')}")
    return fail("app_started", "the platform did not start the generated app (run-app/status running=false)")


def find_key(node: Any, key: str, depth: int = 0) -> Any:
    """First value of `key` anywhere in nested run metadata, or None."""
    if depth > 6:
        return None
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for v in node.values():
            r = find_key(v, key, depth + 1)
            if r is not None:
                return r
    elif isinstance(node, list):
        for v in node[:50]:
            r = find_key(v, key, depth + 1)
            if r is not None:
                return r
    return None


def check_frontend_build(run: dict, local: Optional[dict]) -> CheckResult:
    """Build and tsc ok: from the pipeline's own record when it exposes it, else from a local build of the export."""
    if local is not None:
        if local.get("skipped"):
            return skip("frontend_build_tsc", local["skipped"])
        if local["ok"]:
            return ok("frontend_build_tsc", "tsc --noEmit and vite build passed on the exported frontend")
        return fail("frontend_build_tsc", local["reason"])
    built, tsc = find_key(run.get("phases"), "build_ok"), find_key(run.get("phases"), "tsc_errors")
    if built is None and tsc is None:
        return skip("frontend_build_tsc", "the run record has no build/tsc metadata and no local build was done (use --build-frontend)")
    if built is False or (tsc or 0) > 0:
        return fail("frontend_build_tsc", f"build_ok={built} tsc_errors={tsc}")
    return ok("frontend_build_tsc", f"build_ok={built} tsc_errors={tsc or 0}")


# ---- behaviour checks of the running app -----------------------------------------------------------------------

def check_root_page(probe) -> CheckResult:
    r = probe.request("GET", "/")
    if r.status == 200 and "<" in r.text[:2000]:
        return ok("root_page", "/ serves a page")
    return fail("root_page", f"GET / answered {r.status or r.text[:80]} (a real UI page is expected, not the API explorer or an error)")


def check_public(probe, spec: Optional[dict], items: List[dict]) -> List[CheckResult]:
    out = []
    for it in items:
        name = f"public: {it['name']}"
        if spec is None:
            out.append(fail(name, "cannot find the endpoint: the app exposes no OpenAPI document"))
            continue
        paths = find_ops(spec, it["path_regex"], it.get("method", "GET"))
        if not paths:
            out.append(fail(name, f"no {it.get('method', 'GET')} endpoint matching /{it['path_regex']}/ in the app's OpenAPI"))
            continue
        got = [(p, probe.request(it.get("method", "GET"), p).status) for p in paths[:4]]
        good = [p for p, s in got if s == 200]
        out.append(ok(name, f"{good[0]} answered 200 without a token") if good
                   else fail(name, "no token sent, none answered 200: " + ", ".join(f"{p} -> {s}" for p, s in got)))
    return out


def check_protected(probe, spec: Optional[dict], items: List[dict]) -> List[CheckResult]:
    out = []
    for it in items:
        name = f"protected: {it['name']}"
        method = it.get("method", "GET")
        if spec is None:
            out.append(fail(name, "cannot find the endpoint: the app exposes no OpenAPI document"))
            continue
        paths = find_ops(spec, it["path_regex"], method, with_params=True)
        if not paths:
            out.append(fail(name, f"no {method} endpoint matching /{it['path_regex']}/ in the app's OpenAPI"))
            continue
        got = []
        for p in paths[:4]:
            b = body_for(spec, p, method) if method.upper() in ("POST", "PUT", "PATCH") else None
            got.append((p, probe.request(method, _fill_params(p), json=b).status))
        bad = [f"{p} -> {s}" for p, s in got if s != 401]
        out.append(fail(name, "expected 401 without a token, got: " + ", ".join(bad)) if bad
                   else ok(name, f"{got[0][0]} answered 401 without a token"))
    return out


def check_form_post(probe, spec: Optional[dict], it: dict) -> CheckResult:
    name = f"form: {it['name']}"
    if spec is None:
        return fail(name, "cannot find the endpoint: the app exposes no OpenAPI document")
    paths = find_ops(spec, it["path_regex"], "POST")
    if not paths:
        return fail(name, f"no POST endpoint matching /{it['path_regex']}/ in the app's OpenAPI")
    seen = []
    for p in paths[:4]:
        r = probe.request("POST", p, json=body_for(spec, p, "POST", it.get("body_overrides")))
        if 200 <= r.status < 300:
            return ok(name, f"POST {p} -> {r.status} without a token")
        seen.append(f"{p} -> {r.status} {r.text[:100]}")
    return fail(name, "no 2xx for an anonymous POST with a schema-valid body: " + "; ".join(seen))


def _token_of(r: Resp) -> str:
    b = r.body if isinstance(r.body, dict) else {}
    return str(b.get("access_token") or b.get("token") or "")


def app_login(probe, spec: Optional[dict], creds: dict) -> Tuple[str, str]:
    """(token, reason). Logs in with the platform-reported preview credentials."""
    if spec is None:
        return "", "no OpenAPI document, cannot find the login endpoint"
    if not creds.get("email") or not creds.get("password"):
        return "", f"no usable credentials from preview-credentials: {sorted(creds)}"
    last = "no POST login endpoint in the OpenAPI"
    for p in find_ops(spec, r"login|signin|token", "POST"):
        props = list(((_resolve(((spec["paths"][p]["post"].get("requestBody") or {}).get("content") or {})
                                .get("application/json", {}).get("schema", {}), spec)).get("properties") or {}))
        key = "username" if "username" in props and "email" not in props else "email"
        r = probe.request("POST", p, json={key: creds["email"], "password": creds["password"]})
        if r.status == 200 and _token_of(r):
            return _token_of(r), ""
        last = f"{p} -> {r.status} {r.text[:100]}"
    return "", "login failed: " + last


def check_auth_crud(probe, spec: Optional[dict], it: dict, token: str, why_no_token: str) -> CheckResult:
    """With a login: create a record, read it back, and (if the prompt has a status flow) move it through every state."""
    name = f"crud: {it['name']}"
    if not token:
        return fail(name, why_no_token)
    posts = find_ops(spec, it["path_regex"], "POST")
    if not posts:
        return fail(name, f"no POST endpoint matching /{it['path_regex']}/ in the app's OpenAPI")
    coll = posts[0]
    r = probe.request("POST", coll, json=body_for(spec, coll, "POST", it.get("create_body_overrides")), token=token)
    if not 200 <= r.status < 300 or not isinstance(r.body, dict):
        return fail(name, f"create: POST {coll} with a login -> {r.status} {r.text[:160]}")
    rid = r.body.get("id")
    lst = probe.request("GET", coll, token=token)
    items = lst.body if isinstance(lst.body, list) else (lst.body or {}).get("items", []) if isinstance(lst.body, dict) else []
    if lst.status != 200 or (rid is not None and not any(isinstance(x, dict) and x.get("id") == rid for x in items)):
        return fail(name, f"read back: GET {coll} -> {lst.status}; the created record id={rid} is not in the list")
    field_, steps = it.get("status_field"), it.get("transitions") or []
    if field_ and steps:
        item_paths = [p for p in find_ops(spec, it["path_regex"], "patch", True) + find_ops(spec, it["path_regex"], "put", True)
                      if p.startswith(coll) and "{" in p]
        if not item_paths or rid is None:
            return fail(name, f"created ok, but no PUT/PATCH item endpoint under {coll} to move the status {steps}")
        item = item_paths[0]
        meth = "PATCH" if "patch" in spec["paths"][item] else "PUT"
        for st in steps:
            u = probe.request(meth, re.sub(r"\{[^}]+\}", str(rid), item), json={field_: st}, token=token)
            if not 200 <= u.status < 300 or (isinstance(u.body, dict) and u.body.get(field_) not in (None, st)):
                return fail(name, f"status -> {st!r}: {meth} {item} answered {u.status} {u.text[:140]}")
    return ok(name, f"created id={rid}, listed" + (f", moved through {steps}" if steps else ""))


def check_chat(probe, spec: Optional[dict], it: dict) -> CheckResult:
    name = f"chat: {it['name']}"
    if spec is None:
        return fail(name, "cannot find the endpoint: the app exposes no OpenAPI document")
    paths = find_ops(spec, it["path_regex"], "POST")
    if not paths:
        return fail(name, f"no POST endpoint matching /{it['path_regex']}/ in the app's OpenAPI")
    seen = []
    for p in paths[:4]:
        body = body_for(spec, p, "POST")
        if isinstance(body, dict):      # put the question in the first free-text field
            for k in [k for k in body if k.lower() in ("message", "text", "query", "question", "prompt", "content", "input")][:1] or list(body)[:1]:
                body[k] = it["message"]
        r = probe.request("POST", p, json=body, timeout=120)
        answer = r.text if not isinstance(r.body, dict) else " ".join(str(v) for v in r.body.values() if isinstance(v, str))
        if r.status == 200 and len(answer.strip()) > 10:
            return ok(name, f"POST {p} answered {len(answer)} chars")
        seen.append(f"{p} -> {r.status} {r.text[:120]}")
    return fail(name, "no non-empty 200 answer from the configured LLM: " + "; ".join(seen))


def check_no_accounts(spec: Optional[dict], it: dict) -> CheckResult:
    if spec is None:
        return ok("no_accounts", "no API at all (a static site has no accounts)")
    rx = re.compile(it["forbidden_path_regex"], re.I)
    bad = [p for p in spec.get("paths", {}) if rx.search(p)]
    return fail("no_accounts", "the site has account/auth endpoints although none were asked for: " + ", ".join(bad[:5])) if bad \
        else ok("no_accounts", "no login/register/user endpoints")
