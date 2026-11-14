"""KAN-168 follow-up: what the generated frontend does with spec text, tokens, paths and lists.
Built with the real generators (no model, no npm); the real TypeScript compiler checks syntax."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from aether_os.tests.test_p05_generated_frontend import _tsc, build_frontend


def sources(root: Path):
    for f in sorted(root.rglob("*")):
        if f.is_file() and "node_modules" not in f.parts and f.suffix in (".ts", ".tsx", ".js", ".jsx", ".html", ".json", ".css", ".md", ""):
            yield f, f.read_text(errors="replace")


def tsc_syntax_errors(root: Path) -> list:
    tsc = _tsc()
    if not tsc:
        pytest.skip("typescript (tsc) is not available")
    out = subprocess.run([tsc, "--noEmit", "-p", str(root)], capture_output=True, text=True, timeout=240).stdout
    return [ln for ln in out.splitlines() if re.search(r"error TS(1\d{3}|2304|2552):", ln)]


EVIL = "Acme</title><script>alert(1)</script>\"'{x}`${y}\\"


@pytest.mark.parametrize("domain", ["saas", "crm"])
def test_project_name_cannot_inject_script_or_break_source(tmp_path, monkeypatch, domain):
    # The project name went raw into index.html (a script ran), JSON-LD, JSX text and JS strings.
    root = build_frontend(tmp_path, domain, monkeypatch, project_name=EVIL,
                          extra={"app_tagline": EVIL, "app_brand": {"tagline": EVIL, "headline": EVIL}})
    html = (root / "index.html").read_text()
    assert "<script>alert" not in html and html.count("<script") == 2          # the app's module + JSON-LD only
    ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1)
    assert json.loads(ld)["name"].startswith("Acme")
    json.loads((root / "package.json").read_text())
    for f, text in sources(root):
        assert "<script>alert" not in text and "</title><script" not in text, f
    assert tsc_syntax_errors(root) == []


def test_base_path_is_configurable_and_defaults_to_root(tmp_path, monkeypatch):
    # vite `base` and the router basepath were hard-coded to /app-preview: hosted at the root the app showed nothing.
    root = build_frontend(tmp_path, "saas", monkeypatch)
    vite = (root / "vite.config.ts").read_text()
    assert "process.env.VITE_BASE_PATH || '/'" in vite and "base: BASE_PATH" in vite
    for f, text in sources(root):
        assert "app-preview" not in text, f
    app = (root / "src" / "App.tsx").read_text()
    assert "basepath: import.meta.env.BASE_URL" in app
    assert "window.location.replace(import.meta.env.BASE_URL + 'login')" in (root / "src" / "lib" / "api.ts").read_text()


def test_preview_builds_pass_the_preview_base_through_the_environment(tmp_path, monkeypatch):
    # The AetherOS preview serves the build under /app-preview/, so ITS builds (and only those) set the base.
    import asyncio
    from types import SimpleNamespace
    from aether_os.phases.p05_frontend import build_loop, npm_runner
    seen = []

    async def fake_run(argv, **kw):
        seen.append((list(argv), kw.get("env")))
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(build_loop.phase_exec, "run", fake_run)
    monkeypatch.setattr(npm_runner.phase_exec, "run", fake_run)
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / ".nm_hash").write_text(npm_runner.pkg_hash(tmp_path))
    asyncio.run(build_loop.run_build_loop(tmp_path, max_rounds=1))
    asyncio.run(npm_runner.run_npm_build(tmp_path))
    builds = [env for argv, env in seen if argv[:3] == ["npm", "run", "build"]]
    assert len(builds) == 2 and all(e == {"VITE_BASE_PATH": "/app-preview/"} for e in builds), seen


@pytest.mark.parametrize("domain", ["saas", "crm", "ecommerce"])
def test_login_pages_print_no_credentials_and_one_token_key_is_used(tmp_path, monkeypatch, domain):
    # Login pages printed fixed admin/user passwords; tokens were stored under auth_token, token and access_token.
    root = build_frontend(tmp_path, domain, monkeypatch)
    keys = set()
    for f, text in sources(root):
        for bad in ("Admin1234", "User1234", "demo1234", "Demo credentials"):
            assert bad not in text, (f, bad)
        keys |= set(re.findall(r"localStorage\.(?:get|set|remove)Item\(\s*['\"]([^'\"]*token[^'\"]*)['\"]", text, re.I))
        assert "localStorage.getItem('token')" not in text, f
    assert keys <= {"auth_token", "auth_refresh_token"}, keys
    login = (root / "src" / "lib" / "api.ts").read_text()
    assert "access_token: string; refresh_token: string" in login      # the login pages destructure both


def test_model_written_pages_are_told_to_use_the_api_client_and_the_shared_token(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from aether_os.phases.p05_frontend import llm_page_writer
    prompts = []

    class Fake:
        async def call(self, prompt, **kw):
            prompts.append(prompt)
            return "export default function XPage() { return null }"
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr("aether_os.core.llm.client.get_llm_client", lambda: Fake())
    asyncio.run(llm_page_writer.write_entity_page_llm(
        {"table": "patients", "name": "Patient", "fields": ["id", "name"]}, {"patients": "/api/patients"}, "Demo", "crm",
        "x", None, {}))
    p = prompts[0]
    assert "localStorage" in p and "Never use fetch()" in p and "apiClient" in p
    assert "localStorage.getItem('token')" not in p and "patients → /patients" in p


def test_build_loop_patches_cannot_leave_the_project(tmp_path):
    # build_loop._apply_patch joined the model's path to the project dir without checking: ../../x wrote anywhere.
    from aether_os.phases.p05_frontend.build_loop import _apply_patch
    project = tmp_path / "fe"
    (project / "src").mkdir(parents=True)
    (project / "src" / "a.ts").write_text("const a = 1")
    outside = tmp_path / "secret.txt"
    outside.write_text("const a = 1")
    (project / "src" / "link.ts").symlink_to(outside)
    assert _apply_patch(project, {"file": "src/a.ts", "find": "const a = 1", "replace": "const a = 2"})
    for evil in ("../secret.txt", str(outside), "src/link.ts", "src/../../secret.txt"):
        assert not _apply_patch(project, {"file": evil, "find": "const a = 1", "replace": "pwned"}), evil
    assert outside.read_text() == "const a = 1"


def test_gate2_revisions_go_to_the_shipped_copy(tmp_path, monkeypatch):
    # Gate 2 screenshot and revisions ran on output_dir/frontend, but the customer gets project_dir/frontend (copied
    # once, only when absent): the revisions never shipped, and a re-run shipped the previous run's files.
    import asyncio
    from types import SimpleNamespace
    from aether_os.phases.p05_frontend import approval_gates, task_agent
    seen = []

    async def shot(frontend_dir, out):
        out.write_text("png")
        return True

    async def revise(instr, frontend_dir, domain, name):
        seen.append(Path(frontend_dir))
        (Path(frontend_dir) / "src" / "REVISED.txt").write_text("x")

    async def critique(*a, **k):
        return "make it nicer"
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setattr(task_agent, "take_preview_screenshot", shot)
    monkeypatch.setattr(task_agent, "apply_gate2_revisions", revise)
    monkeypatch.setattr(approval_gates, "vlm_rubric_critique", critique)
    data = {"project_name": "Demo", "domain": "crm", "architecture_json": {"database_schema": [{"table": "patients", "columns": ["id", "name"]}]},
            "raw_input": "x", "autonomous_mode": True}
    stale = tmp_path / "frontend" / "src"
    stale.mkdir(parents=True)
    (stale / "STALE.txt").write_text("old run")
    result = asyncio.run(task_agent.run(SimpleNamespace(input_data=data, domain="crm", project_id="p"), [], tmp_path / "p05_frontend"))
    shipped = Path(result.output_path)
    assert shipped == tmp_path / "frontend" and seen and all(s == shipped for s in seen), (shipped, seen)
    assert (shipped / "src" / "REVISED.txt").exists()
    assert (shipped / "src" / "App.tsx").exists()           # refreshed from this run, not the stale copy


def test_preview_server_is_loopback_only_and_playwright_install_does_not_block_the_loop(tmp_path, monkeypatch):
    # take_preview_screenshot ran `playwright install` with a blocking subprocess.run inside the coroutine (the event
    # loop froze for up to two minutes) and served the build with http.server's default bind on every interface.
    import asyncio
    import threading
    from types import SimpleNamespace
    from aether_os.phases.p05_frontend import preview
    ran_in, popen_args = [], []

    def fake_run(argv, **kw):
        ran_in.append(threading.current_thread())
        return SimpleNamespace(returncode=0)

    class Proc:
        def terminate(self):
            pass
    monkeypatch.setattr(preview.subprocess, "run", fake_run)
    monkeypatch.setattr(preview.subprocess, "Popen", lambda argv, **kw: popen_args.append(argv) or Proc())
    (tmp_path / "dist").mkdir()
    asyncio.run(preview.take_preview_screenshot(tmp_path, tmp_path / "shot.png"))
    assert ran_in and ran_in[0] is not threading.main_thread()
    argv = popen_args[0]
    assert argv[argv.index("--bind") + 1] == "127.0.0.1"


def test_gate_fails_for_a_structurally_broken_project(tmp_path, monkeypatch):
    # The gate returned passed=True at the end whatever it found, and failed early only when EVERY issue was a
    # missing file: a project without App.tsx (or without the router dependency) passed.
    from aether_os.phases.base import TaskResult
    from aether_os.phases.p05_frontend import gate
    monkeypatch.setenv("ENVIRONMENT", "test")
    root = build_frontend(tmp_path, "crm", monkeypatch)
    check = lambda: gate.validate(TaskResult(output_path=str(root), confidence=1.0, metadata={}, success=True))
    assert check().passed
    (root / "src" / "App.tsx").unlink()
    out = check()
    assert not out.passed and any("App.tsx" in i for i in out.issues)
    (root / "src" / "App.tsx").write_text("export default function App() { return null }")
    pkg = json.loads((root / "package.json").read_text())
    del pkg["dependencies"]["@tanstack/react-router"]
    (root / "package.json").write_text(json.dumps(pkg))
    assert not check().passed


def test_list_and_dropdown_requests_match_what_the_backend_serves(tmp_path, monkeypatch):
    # FK dropdowns requested /api/api/x (the client's baseURL already ends in /api) and only the first 20 rows;
    # the calendar page asked for 500 rows, the backend rejects more than 200 (422); the IR backend named its page-size
    # parameter `limit` (<=100) while the client sends page_size.
    root = build_frontend(tmp_path, "crm", monkeypatch)
    modal = (root / "src" / "components" / "CrudModal.tsx").read_text()
    assert "endpoint.replace(/^\\/api(?=\\/)/, '')" in modal and "page_size: 200" in modal
    for f, text in sources(root):
        for n in re.findall(r"\.list\(\s*1\s*,\s*(\d+)\s*\)", text):
            assert int(n) <= 200, (f, n)
    assert not tsc_syntax_errors(root)


def test_csv_export_defuses_formulas_and_includes_ids(tmp_path, monkeypatch):
    # Exported cells beginning with = + - @ ran as formulas in Excel/Sheets (CSV injection); the record id was missing.
    import shutil
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available")
    root = build_frontend(tmp_path, "crm", monkeypatch)
    text = next(t for t in (p.read_text() for p in (root / "src" / "pages").glob("*Page.tsx")) if "escapeCell" in t)
    body = re.search(r"const escapeCell = .*?const csv = [^\n]*", text, re.S).group(0)
    js = ("const columns=[{id:'name',header:'Name'},{id:'note',header:'Note'}];"
          "const data=[{id:7,name:'=HYPERLINK(\"http://x\")',note:'a,b'},{id:8,name:'-5',note:5}];"
          "const T=(x)=>x;" + re.sub(r": (unknown|string)\b", "", re.sub(r"\(item as any\)", "item", body).replace("(v: unknown)", "(v)")
          .replace("as string", "")) + ";console.log(JSON.stringify(csv))")
    out = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    csv = json.loads(out.stdout)
    assert csv.startswith("﻿id,Name,Note") and "7,\"'=HYPERLINK" in csv and "\"a,b\"" in csv and "\r\n8,'-5,5" in csv, csv


def test_scaffold_route_map_reads_api_prefixed_routes(tmp_path):
    # api_routes.json lists the backend's real paths (/api/patients). The first path segment was taken as the table, so
    # every route became the table "api", and a kept "/api/x" path was requested as /api/api/x.
    from aether_os.phases.p05_frontend.scaffold import read_architecture
    routes = [{"method": "GET", "path": "/api/patients"}, {"method": "GET", "path": "/api/patients/{item_id}"},
              {"method": "POST", "path": "/api/patients"}, {"method": "GET", "path": "/api/stats"},
              {"method": "GET", "path": "/api/auth/me"}, {"method": "GET", "path": "/health"},
              {"method": "GET", "path": "/orders/"}]
    (tmp_path / "api_routes.json").write_text(json.dumps(routes))
    arch = read_architecture({"api_routes_path": str(tmp_path / "api_routes.json"),
                              "architecture_json": {"database_schema": [{"table": "patients", "columns": ["id"]}]}})
    assert arch["api_route_map"] == {"patients": "/patients", "orders": "/orders"}


def test_generated_docker_compose_has_no_default_secret(tmp_path, monkeypatch):
    # SECRET_KEY defaulted to a placeholder that is the same in every generated app.
    root = build_frontend(tmp_path / "fe", "crm", monkeypatch)
    compose = (root.parent / "docker-compose.yml").read_text()
    assert "SECRET_KEY: ${SECRET_KEY:?" in compose and "changeme" not in compose


def _run_cloud_console(tmp_path, monkeypatch, env="test", build=None):
    import asyncio
    from types import SimpleNamespace
    from aether_os.phases.p05_frontend import task_agent
    monkeypatch.setenv("ENVIRONMENT", env)
    if build is not None:
        monkeypatch.setattr(task_agent, "run_npm_build", build)
    data = {"project_name": "Cloud</title><script>x</script>", "build_profile": {"build_type": "cloud_platform"},
            "services": [{"name": "compute", "description": "VMs", "icon": "x"}]}
    return asyncio.run(task_agent.run(SimpleNamespace(input_data=data, domain="saas", project_id="p"), [], tmp_path / "p05"))


def test_cloud_console_has_a_login_route_and_logout_goes_there(tmp_path, monkeypatch):
    # Logout sent the browser to /login, a route nothing defined; there was no login page and the console reached the
    # API without a token. Names from the spec were written raw into JSX.
    result = _run_cloud_console(tmp_path, monkeypatch)
    src = Path(result.output_path) / "src"
    app = (src / "App.jsx").read_text()
    login = (src / "pages" / "Login.jsx").read_text()
    assert "navigate('/login')" in app and "window.location.href = '/login'" not in app
    assert "pathname === '/login'" in app and "<Navigate to=\"/login\"" in app
    assert "/api/auth/login" in login and "access_token" in login and 'htmlFor="email"' in login
    assert "<script>" not in (Path(result.output_path) / "index.html").read_text()
    assert "Math.random" not in (src / "pages" / "Dashboard.jsx").read_text()


def test_cloud_console_is_not_reported_successful_without_a_build(tmp_path, monkeypatch):
    # The cloud console branch returned success with confidence 0.9 without building anything.
    untested = _run_cloud_console(tmp_path / "a", monkeypatch)
    assert untested.confidence <= 0.5 and untested.metadata["built"] is False

    async def failing(_dir):
        return False
    failed = _run_cloud_console(tmp_path / "b", monkeypatch, env="production", build=failing)
    assert failed.success is False and failed.confidence < 0.5

    async def ok(_dir):
        return True
    built = _run_cloud_console(tmp_path / "c", monkeypatch, env="production", build=ok)
    assert built.success and built.confidence == 0.9 and built.metadata["built"] is True


def test_storefront_and_dashboard_show_no_invented_content(tmp_path, monkeypatch):
    # Promo banner with a discount code, fake testimonials with names, "free shipping" badges, stock photos from
    # picsum.photos, random "Save N%" badges, invented ratings and a "Live" label on hard-coded chart data.
    for domain in ("ecommerce", "crm"):
        root = build_frontend(tmp_path / domain, domain, monkeypatch)
        for f, text in sources(root):
            for bad in ("picsum.photos", "WELCOME10", "Testimonials", "Sarah M.", "Math.floor(Math.random()",
                        "Free shipping", "30-day return", "Trusted by thousands", "(price * 1.2)"):
                assert bad not in text, (f, bad)
            if "TREND_DATA" in text:
                assert "Sample chart data" in text and "> Live" not in text, f
        assert not tsc_syntax_errors(root)
