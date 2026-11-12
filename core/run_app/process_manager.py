"""
AetherOS — RunAppManager
========================
Service class that encapsulates all the logic for starting a generated
application preview (npm install, vite build, SQLite swap, uvicorn launch).

This is the prerequisite for splitting factory_runs_router.py: moving the
heavy start_run_app body here lets run_app_router.py delegate to this class
instead of duplicating 800+ lines in the router layer.

Usage
-----
    from aether_os.core.run_app.process_manager import RunAppManager
    result = await RunAppManager().start(run_id, org_id, user)

The return value is the same dict that the original POST /run-app endpoint
returned: {status, port, pid, backend_dir, mode, …}.

No HTTP types (Request, HTTPException) are imported at module level so this
class is importable from the orchestrator layer without pulling in FastAPI.
"""
from __future__ import annotations

import asyncio
import logging
import pathlib
from typing import Any, Dict, Optional

from aether_os.core.run_app import preview_state, preview_token
from aether_os.core.run_app.child_env import child_env
from aether_os.core.run_app.sandboxed import pip_install, venv_python
from aether_os.core.sandbox.docker_backend import labels_for
from aether_os.core.sandbox.runner import SandboxUnavailable, get_runner, sandbox_dirs
from aether_os.core.run_app.process_manager_helpers import (
    api_explorer_html,
    stub_main_py,
    patch_generated_project,
)

logger = logging.getLogger(__name__)

# ── Module-level shared state helpers ─────────────────────────────────────────

def _get_app_procs() -> Dict[str, Any]:
    from aether_os.core.app_state import get_all_procs
    return get_all_procs()


def _get_app_ports() -> Dict[str, int]:
    from aether_os.core.app_state import get_all_ports
    return get_all_ports()


# Maps run_id → project root dir (used by proxy to locate static frontend)
_APP_DIRS: Dict[str, str] = {}


def get_active_preview_dir() -> Optional[str]:
    """Return the project dir of the most recently started app preview."""
    return _APP_DIRS.get("__current__")


# ── RunAppManager ──────────────────────────────────────────────────────────────

class RunAppManager:
    """Manages lifecycle of generated-app preview processes."""

    async def start(
        self,
        run_id: str,
        org_id: str,
        user: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Install dependencies, build the React frontend, patch generated code,
        and launch uvicorn for the generated backend.

        Raises fastapi.HTTPException on unrecoverable errors so it can be
        called directly from a router endpoint.
        """
        from fastapi import HTTPException
        from aether_os.core.projects import get_project_manager
        from aether_os.core.audit.ledger import get_ledger
        from aether_os.core.services.run_app_service import acquire_free_port

        _run_procs = _get_app_procs()
        _run_ports = _get_app_ports()
        existing = _run_procs.get(run_id)
        # A handle rebuilt from a stale state file (reused pid) is not "running".
        _live_port = await asyncio.to_thread(preview_state.live_port, run_id)
        if existing is not None and _live_port:
            return {"status": "already_running", "pid": existing.pid, "port": _live_port}

        run_detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
        if not run_detail:
            raise HTTPException(status_code=404, detail="Run not found")

        project_id = run_detail.get("project_id") or run_id
        root_dir = get_project_manager().get_project_dir(project_id).resolve()
        # Every step below runs generated code (install hooks, builds, the app): sandboxed or not at all.
        try:
            runner = await asyncio.to_thread(get_runner)
        except SandboxUnavailable as exc:
            logger.error("RunAppManager: refusing to run generated code for %s: %s", run_id, exc)
            raise HTTPException(status_code=503, detail=f"Sandbox unavailable: {exc}")
        port = await acquire_free_port()

        # ── Locate backend entry point ─────────────────────────────────────────
        backend_dir: Optional[pathlib.Path] = None
        candidates = [
            root_dir / "p04_backend" / "backend_codegen",
            root_dir / "p03_scaffolding",
        ]
        for cand in candidates:
            if cand.is_dir():
                subdirs = [d for d in cand.iterdir() if d.is_dir() and (d / "src" / "main.py").exists()]
                if subdirs:
                    backend_dir = subdirs[0]
                    break
                if (cand / "src" / "main.py").exists():
                    backend_dir = cand
                    break

        if not backend_dir:
            raise HTTPException(
                status_code=422,
                detail="Could not locate backend src/main.py in generated project.",
            )

        log_path = root_dir / "run_app.log"
        # Generated code and its install/build scripts never see the platform's environment.
        _tool_env = child_env(PIP_DISABLE_PIP_VERSION_CHECK="1", **sandbox_dirs(root_dir))

        # ── Install Python dependencies (into the run's venv, never the platform's) ──
        _py = await asyncio.to_thread(venv_python, runner, root_dir, _tool_env)
        await asyncio.to_thread(pip_install, runner, root_dir, _py, ["aiosqlite", "httpx"], _tool_env, 60)
        req_file = backend_dir / "requirements.txt"
        if req_file.exists():
            _req_lines = req_file.read_text().splitlines()
            _lite_reqs = [
                ln for ln in _req_lines
                if not any(pkg in ln.lower() for pkg in ("psycopg2", "asyncpg", "pg8000"))
            ]
            _lite_req_path = root_dir / "_preview_requirements.txt"
            _lite_req_path.write_text("\n".join(_lite_reqs))
            with open(log_path, "w") as _lf:
                _lf.write("[AetherOS] Installing backend deps (SQLite preview mode)\n")
            await asyncio.to_thread(pip_install, runner, root_dir, _py, ["-r", str(_lite_req_path)],
                                    _tool_env, 120)

        # ── Locate frontend ────────────────────────────────────────────────────
        _frontend_candidates = [
            root_dir / "p05_frontend" / "frontend",
            root_dir / "frontend",
        ]
        frontend_dir = next(
            (d for d in _frontend_candidates if (d / "package.json").exists()), None
        )
        frontend_dist = (frontend_dir / "dist") if frontend_dir else None

        # ── Build React frontend ───────────────────────────────────────────────
        node_bin = runner.tool("node")
        npm_bin = runner.tool("npm")
        if node_bin and npm_bin and frontend_dir and frontend_dir.is_dir():
            import re as _re_cfg
            for _cfg_name in ("vite.config.ts", "vite.config.js"):
                _cfg_path = frontend_dir / _cfg_name
                if _cfg_path.exists():
                    _cfg = _cfg_path.read_text()
                    if "base:" not in _cfg and "basePath" not in _cfg:
                        _cfg = _cfg.replace(
                            "export default defineConfig({",
                            "export default defineConfig({\n  base: '/app-preview/',",
                        )
                        _cfg_path.write_text(_cfg)
                    break

            _env_prod = frontend_dir / ".env.production"
            _correct_env = "VITE_API_URL=/app-preview/api\n"
            _env_changed = not _env_prod.exists() or _env_prod.read_text() != _correct_env
            _env_prod.write_text(_correct_env)

            for _api_src in ("src/lib/api.ts", "src/lib/api.tsx", "src/api.ts", "src/api.js"):
                _api_path = frontend_dir / _api_src
                if _api_path.exists():
                    _api_code = _api_path.read_text()
                    _patched = False
                    for _wrong in (
                        "baseURL: '/api'", 'baseURL: "/api"',
                        "baseURL:'/api'", 'baseURL:"/api"',
                    ):
                        if _wrong in _api_code:
                            _api_code = _api_code.replace(_wrong, "baseURL: '/app-preview/api'")
                            _patched = True
                    if _patched:
                        _api_path.write_text(_api_code)
                        _env_changed = True
                    break

            for _src_name in ("src/App.tsx", "src/App.jsx", "src/main.tsx", "src/main.jsx"):
                _src_path = frontend_dir / _src_name
                if _src_path.exists():
                    _src = _src_path.read_text()
                    if "createRouter" in _src and "basepath" not in _src and "basePath" not in _src:
                        _src = _src.replace(
                            "createRouter({ routeTree })",
                            "createRouter({ routeTree, basepath: '/app-preview' })",
                        )
                        _src_path.write_text(_src)
                    elif "BrowserRouter" in _src and "basename" not in _src:
                        _src = _src.replace("BrowserRouter>", "BrowserRouter basename='/app-preview'>")
                        _src = _src.replace("BrowserRouter />", "BrowserRouter basename='/app-preview' />")
                        _src_path.write_text(_src)

            _dist_already_built = (
                not _env_changed
                and frontend_dist
                and frontend_dist.is_dir()
                and any(frontend_dist.iterdir())
            )
            if not _dist_already_built:
                with open(log_path, "a") as _lf:
                    _lf.write(f"[AetherOS] Building React frontend from {frontend_dir}...\n")
                # npm's cache lives in the sandbox HOME (run dir): no cache shared across runs.
                _npm_install_r = await asyncio.to_thread(
                    runner.run, [npm_bin, "install", "--silent"],
                    run_dir=root_dir, cwd=frontend_dir, timeout=300, env=_tool_env, network=True,
                )
                if _npm_install_r.returncode != 0:
                    _npm_err = (_npm_install_r.stderr or b"").decode(errors="replace")[-400:]
                    with open(log_path, "a") as _lf:
                        _lf.write(
                            f"[AetherOS] npm install failed (rc={_npm_install_r.returncode}):\n{_npm_err}\n"
                        )

                import json as _json_ts
                for _ts_name in ("tsconfig.json", "tsconfig.app.json"):
                    _ts_path = frontend_dir / _ts_name
                    if _ts_path.exists():
                        try:
                            _ts = _json_ts.loads(_ts_path.read_text())
                            _co = _ts.setdefault("compilerOptions", {})
                            _co.update({
                                "skipLibCheck": True,
                                "strict": False,
                                "noImplicitAny": False,
                                "allowSyntheticDefaultImports": True,
                                "noUnusedLocals": False,
                                "noUnusedParameters": False,
                            })
                            _ts_path.write_text(_json_ts.dumps(_ts, indent=2))
                        except Exception as exc:
                            logger.warning("RunAppManager: could not patch %s: %s", _ts_name, exc)

                for _vc_name in ("vite.config.ts", "vite.config.js"):
                    _vc_path = frontend_dir / _vc_name
                    if _vc_path.exists():
                        _vc = _vc_path.read_text()
                        if "plugin-react-swc" in _vc:
                            _swc_installed = (
                                frontend_dir / "node_modules" / "@vitejs" / "plugin-react-swc"
                            ).is_dir()
                            if not _swc_installed:
                                _vc = _vc.replace("@vitejs/plugin-react-swc", "@vitejs/plugin-react")
                                _vc_path.write_text(_vc)
                        break

                _npx_bin = runner.tool("npx") or "npx"
                _node_env = child_env(
                    NODE_OPTIONS="--max-old-space-size=384",
                    ESBUILD_WORKER_THREADS="false",
                    **sandbox_dirs(root_dir),
                )
                _vite_result = await asyncio.to_thread(
                    runner.run, [_npx_bin, "vite", "build"],
                    run_dir=root_dir, cwd=frontend_dir, timeout=300, env=_node_env,
                )
                if _vite_result.returncode != 0:
                    _err = (_vite_result.stderr or b"").decode(errors="replace")[-800:]
                    with open(log_path, "a") as _lf:
                        _lf.write(
                            f"[AetherOS] Vite build failed (rc={_vite_result.returncode}):\n{_err}\n"
                        )
                    _oom = (
                        _vite_result.returncode in (-9, 137)
                        or "Killed" in _err
                        or "responseCallbacks" in _err
                        or "write EPIPE" in _err
                        or "read ECONNRESET" in _err
                    )
                    _node_env2 = {
                        **_node_env,
                        "NODE_OPTIONS": "--max-old-space-size=192",
                        "ESBUILD_WORKER_THREADS": "false",
                    } if _oom else _node_env
                    await asyncio.to_thread(
                        runner.run, [npm_bin, "install", "--save-dev", "@vitejs/plugin-react", "--silent"],
                        run_dir=root_dir, cwd=frontend_dir, timeout=120, env=_tool_env, network=True,
                    )
                    if _oom:
                        for _vc_name2 in ("vite.config.ts", "vite.config.js"):
                            _vc_path2 = frontend_dir / _vc_name2
                            if _vc_path2.exists():
                                _vc2 = _vc_path2.read_text()
                                if "minify" not in _vc2 and "build:" not in _vc2:
                                    _vc2 = _vc2.replace(
                                        "export default defineConfig({",
                                        "export default defineConfig({\n"
                                        "  build: { minify: false, chunkSizeWarningLimit: 4000 },",
                                    )
                                    _vc_path2.write_text(_vc2)
                                break
                    _vite_result2 = await asyncio.to_thread(
                        runner.run, [_npx_bin, "vite", "build"],
                        run_dir=root_dir, cwd=frontend_dir, timeout=300, env=_node_env2,
                    )
                    if _vite_result2.returncode != 0:
                        _err2 = (_vite_result2.stderr or b"").decode(errors="replace")[-400:]
                        with open(log_path, "a") as _lf:
                            _lf.write(
                                f"[AetherOS] Frontend build failed after retry:\n{_err2}\n"
                                "[AetherOS] Using API-explorer fallback\n"
                            )

                if frontend_dist and frontend_dist.is_dir() and any(frontend_dist.iterdir()):
                    with open(log_path, "a") as _lf:
                        _lf.write(f"[AetherOS] Frontend built → {frontend_dist}\n")
                else:
                    # Build failed: synthesise a lightweight API-explorer page
                    frontend_dist = root_dir / "_preview_ui"
                    frontend_dist.mkdir(exist_ok=True)
                    _project_label = (
                        run_detail.get("project_name") or f"project-{run_id[:8]}"
                    ).replace("'", "\\'")
                    (frontend_dist / "index.html").write_text(
                        api_explorer_html(_project_label, run_id)
                    )
                    with open(log_path, "a") as _lf:
                        _lf.write(
                            f"[AetherOS] Using API-explorer fallback UI at {frontend_dist}\n"
                        )
            else:
                with open(log_path, "a") as _lf:
                    _lf.write("[AetherOS] Skipping frontend rebuild — dist already exists\n")

        # ── Patch all generated source files ───────────────────────────────────
        # (main.py, models.py, schemas.py, crud.py, auth.py, seed.py, tsx imports)
        _preview_email, _PREVIEW_PASSWORD = patch_generated_project(
            backend_dir=backend_dir,
            root_dir=root_dir,
            frontend_dir=frontend_dir,
            frontend_dist=frontend_dist,
            log_path=log_path,
        )

        # ── Start uvicorn ──────────────────────────────────────────────────────
        _env = child_env(
            DATABASE_URL=f"sqlite+aiosqlite:///{root_dir}/preview.db",
            PYTHONPATH=str(backend_dir / "src"),
            **sandbox_dirs(root_dir),
        )
        # Per-launch marker on the command line: ties the recorded pid to this launch.
        _nonce = preview_state.new_nonce()
        _nonce_args = preview_state.nonce_args(_nonce)

        _alembic_ini = backend_dir / "alembic.ini"
        if _alembic_ini.exists():
            with open(log_path, "a") as _lf:
                _lf.write("[AetherOS] Running alembic upgrade head...\n")
            _alembic_result = await asyncio.to_thread(
                runner.run, [_py, "-m", "alembic", "upgrade", "head"],
                run_dir=root_dir, cwd=backend_dir, timeout=60, env=_env,
            )
            with open(log_path, "a") as _lf:
                if _alembic_result.returncode == 0:
                    _lf.write("[AetherOS] Alembic migrations applied successfully.\n")
                else:
                    _err = (_alembic_result.stderr or b"").decode(errors="replace")[-400:]
                    _lf.write(
                        f"[AetherOS] Alembic migration failed (falling back to create_all): {_err}\n"
                    )

        _labels = labels_for(run_id, _nonce)

        def _uvicorn(app_ref: str) -> list:
            return [_py, "-m", "uvicorn", app_ref,
                    "--host", runner.bind_host, "--port", str(port), *_nonce_args]

        def _log(line: str) -> None:
            with open(log_path, "a") as _lf:
                _lf.write(line)

        def _try_start_backend():
            _log(f"[AetherOS] Starting generated backend on port {port} from {backend_dir} "
                 f"(sandbox: {runner.name})\n")
            proc = runner.start(_uvicorn("src.main:app"), run_dir=root_dir, cwd=backend_dir,
                                env=_env, log_path=log_path, port=port, labels=_labels)
            if proc.poll() is not None:
                _log("[AetherOS] Backend crashed — falling back to frontend-only server\n")
                return None
            return proc

        def _start_frontend_server():
            _stub_dir = root_dir / "_preview_stub"
            _stub_dir.mkdir(exist_ok=True)
            _stub_main = _stub_dir / "main.py"
            _dist_path = (
                str(frontend_dist).replace("\\", "/")
                if frontend_dist and frontend_dist.is_dir()
                else None
            )
            _stub_needs_write = (
                not _stub_main.exists()
                or '"data": []' in _stub_main.read_text()
                or "_MOCK_ROWS" not in _stub_main.read_text()
            )
            if not _stub_needs_write:
                _log("[AetherOS] Reusing existing custom preview stub\n")
            else:
                _stub_main.write_text(stub_main_py(_dist_path))
                _log(f"[AetherOS] Starting frontend-only preview server on port {port}\n")
            return runner.start(_uvicorn("main:app"), run_dir=root_dir, cwd=_stub_dir,
                                env=_tool_env, log_path=log_path, port=port, labels=_labels)

        # Served only by the preview server; opening it needs POST .../preview-session first.
        _preview_url = f"{preview_token.preview_origin() or ''}/app-preview/"
        try:
            proc = await asyncio.to_thread(_try_start_backend)
            await asyncio.sleep(2)
            mode = "backend"
            if proc is None:
                if frontend_dist and frontend_dist.is_dir():
                    proc = await asyncio.to_thread(_start_frontend_server)
                    mode = "frontend_only"
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=(
                            "Generated backend crashed and no frontend build available. "
                            "Check the run log."
                        ),
                    )

            _run_procs[run_id] = proc
            _run_ports[run_id] = port
            _APP_DIRS[run_id] = str(root_dir)
            _APP_DIRS["__current__"] = str(root_dir)

            try:
                from aether_os.core.app_state import set_app_state as _sas, set_proc as _sp_fn
                _sp_fn(run_id, proc)
                await _sas(run_id, port=port, pid=proc.pid, mode=mode, app_dir=str(root_dir))
            except Exception as exc:
                logger.warning("RunAppManager: could not update app_state for %s: %s", run_id, exc)

            try:
                preview_state.write_state(root_dir / preview_state.STATE_FILE, run_id,
                                          port, proc.pid, _nonce, mode,
                                          container=getattr(proc, "container_id", None))
            except Exception as exc:
                logger.warning("RunAppManager: could not write run_app_state.json for %s: %s", run_id, exc)

            try:
                from aether_os.core.db_utils import async_update_run_live_url as _aulul
                await _aulul(run_id, _preview_url)
            except Exception as exc:
                logger.warning("RunAppManager: could not update live_url for %s: %s", run_id, exc)

            return {
                "status": "started",
                "port": port,
                "pid": proc.pid,
                "backend_dir": str(backend_dir),
                "mode": mode,
                "frontend_built": bool(
                    frontend_dir
                    and (frontend_dir / "dist").is_dir()
                    and any((frontend_dir / "dist").iterdir())
                ),
                "log": str(log_path),
                "preview_email": _preview_email,
                "preview_password": _PREVIEW_PASSWORD,
                "live_url": _preview_url,
                "preview_url": _preview_url,
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start app: {e}")

