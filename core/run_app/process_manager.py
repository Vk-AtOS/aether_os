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
import json
import logging
import os
import pathlib
import subprocess as _sp
import sys
import textwrap
from typing import Any, Dict, Optional

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
        import shutil as _sh

        _run_procs = _get_app_procs()
        _run_ports = _get_app_ports()
        existing = _run_procs.get(run_id)
        if existing is not None and existing.poll() is None:
            return {
                "status": "already_running",
                "pid": existing.pid,
                "port": _run_ports.get(run_id, int(os.environ.get("RUN_APP_PORT", "8001"))),
            }

        run_detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
        if not run_detail:
            raise HTTPException(status_code=404, detail="Run not found")

        project_id = run_detail.get("project_id") or run_id
        root_dir = get_project_manager().get_project_dir(project_id).resolve()
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

        # ── Install Python dependencies ────────────────────────────────────────
        _sp.run(
            [sys.executable, "-m", "pip", "install", "aiosqlite", "httpx", "-q",
             "--no-warn-script-location"],
            capture_output=True, timeout=60,
        )
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
            _sp.run(
                [sys.executable, "-m", "pip", "install", "-r", str(_lite_req_path), "-q",
                 "--no-warn-script-location"],
                capture_output=True, timeout=120,
            )

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
        node_bin = _sh.which("node")
        npm_bin = _sh.which("npm")
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
                _npm_cache = os.path.expanduser("~/.aether_os/npm_cache")
                _npm_install_r = _sp.run(
                    [npm_bin, "install", "--silent", "--cache", _npm_cache],
                    cwd=str(frontend_dir), capture_output=True, timeout=300,
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
                        except Exception:
                            pass

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

                _npx_bin = _sh.which("npx") or "npx"
                _node_env = {
                    **os.environ,
                    "NODE_OPTIONS": "--max-old-space-size=384",
                    "ESBUILD_WORKER_THREADS": "false",
                }
                _vite_result = _sp.run(
                    [_npx_bin, "vite", "build"],
                    cwd=str(frontend_dir), capture_output=True, timeout=300,
                    env=_node_env,
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
                    _sp.run(
                        [npm_bin, "install", "--save-dev", "@vitejs/plugin-react", "--silent",
                         "--cache", _npm_cache],
                        cwd=str(frontend_dir), capture_output=True, timeout=120,
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
                    _vite_result2 = _sp.run(
                        [_npx_bin, "vite", "build"],
                        cwd=str(frontend_dir), capture_output=True, timeout=300,
                        env=_node_env2,
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
                        self._api_explorer_html(_project_label, run_id)
                    )
                    with open(log_path, "a") as _lf:
                        _lf.write(
                            f"[AetherOS] Using API-explorer fallback UI at {frontend_dist}\n"
                        )
            else:
                with open(log_path, "a") as _lf:
                    _lf.write("[AetherOS] Skipping frontend rebuild — dist already exists\n")

        # ── Patch main.py ──────────────────────────────────────────────────────
        main_py = backend_dir / "src" / "main.py"
        if main_py.exists():
            import re as _re
            content = main_py.read_text()
            content = content.replace("class_=typing.AsyncSession", "class_=AsyncSession")

            if _re.search(r"^import timezone\b", content, _re.MULTILINE):
                content = _re.sub(
                    r"^import timezone\b[^\n]*\n?", "", content, flags=_re.MULTILINE
                )
                if "from datetime import" in content:
                    content = _re.sub(
                        r"from datetime import ([^\n]+)",
                        lambda m: m.group(0)
                        if "timezone" in m.group(1)
                        else m.group(0).rstrip() + ", timezone",
                        content,
                        count=1,
                    )
                else:
                    content = "from datetime import timezone\n" + content

            _sa_import_line = _re.search(
                r"^from sqlalchemy import ([^\n]+)", content, _re.MULTILINE
            )
            if _sa_import_line:
                _existing = _sa_import_line.group(1)
                _needed = [
                    "Float", "JSON", "BigInteger", "Numeric", "LargeBinary", "UniqueConstraint"
                ]
                _missing = [t for t in _needed if t not in _existing]
                if _missing:
                    content = content.replace(
                        _sa_import_line.group(0),
                        _sa_import_line.group(0) + ", " + ", ".join(_missing),
                    )

            _effective_dist = (
                frontend_dist if (frontend_dist and frontend_dist.is_dir()) else None
            )
            if _effective_dist is None:
                _preview_ui_fallback = root_dir / "_preview_ui"
                if (_preview_ui_fallback / "index.html").exists():
                    _effective_dist = _preview_ui_fallback
            _dist_str = str(_effective_dist).replace("\\", "/") if _effective_dist else ""
            _will_add_spa = bool(_dist_str)
            with open(log_path, "a") as _lf:
                _lf.write(
                    f"[AetherOS] main.py patch: _will_add_spa={_will_add_spa}, "
                    f"_dist_str={_dist_str!r}\n"
                )
            if _will_add_spa:
                content = _re.sub(
                    r'\n@app\.get\(["\']\/["\'][^)]*\)\n(?:async )?def [^\n]+\n(?:    [^\n]+\n)*',
                    "\n",
                    content,
                )
                content += f"""

# AetherOS: serve the Vite-built frontend for all non-API paths (including root)
import pathlib as _spa_pathlib
_FRONTEND_DIST = _spa_pathlib.Path(r"{_dist_str}")

from fastapi.responses import FileResponse as _SpaFileResponse

@app.get("/", include_in_schema=False)
def _spa_root():
    return _SpaFileResponse(str(_FRONTEND_DIST / "index.html"))

@app.get("/{{path:path}}", include_in_schema=False)
def _spa_catchall(path: str = ""):
    _f = _FRONTEND_DIST / path
    if _f.is_file():
        return _SpaFileResponse(str(_f))
    return _SpaFileResponse(str(_FRONTEND_DIST / "index.html"))
"""
            else:
                if not _re.search(r'@app\.get\(["\']\/["\']', content):
                    content += (
                        '\n\n@app.get("/", include_in_schema=False)\n'
                        "def _root_redirect():\n"
                        "    from fastapi.responses import RedirectResponse\n"
                        '    return RedirectResponse(url="/docs")\n'
                    )

            if _re.search(r"^@app\.", content, _re.MULTILINE) and not _re.search(
                r"^(?:app|application)\s*=\s*FastAPI\s*\(", content, _re.MULTILINE
            ):
                _boilerplate = (
                    "from fastapi import FastAPI, HTTPException, Depends\n"
                    "from fastapi.middleware.cors import CORSMiddleware\n"
                    "import os as _os, uuid as _uuid, sqlite3 as _sqlite3\n"
                    "from datetime import datetime as _dt\n"
                    "app = FastAPI(title='Generated App', version='1.0.0')\n"
                    "app.add_middleware(CORSMiddleware, allow_origins=['*'], "
                    "allow_credentials=True, allow_methods=['*'], allow_headers=['*'])\n"
                    "db = {}\n\n"
                )
                content = _boilerplate + content

            main_py.write_text(content)

            run_preview_py = root_dir / "run_preview.py"
            _dist_str2 = (
                str(frontend_dist).replace("\\", "/")
                if frontend_dist and frontend_dist.is_dir()
                else ""
            )
            preview_content = textwrap.dedent(f"""\
                \"\"\"AetherOS run-preview entrypoint — VPS only, not distributed.\"\"\"
                import os
                import pathlib
                import sys

                _PROJECT_DIR = pathlib.Path(__file__).parent
                sys.path.insert(0, str(_PROJECT_DIR / "src"))

                _PREVIEW_DB = _PROJECT_DIR / "preview.db"
                _DIST = _PROJECT_DIR / "p05_frontend" / "frontend" / "dist"

                os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{{_PREVIEW_DB}}")
                os.environ.setdefault("SECRET_KEY", "aetheros-preview-secret-not-for-production")

                from main import app  # noqa: E402

                if _DIST.is_dir():
                    from fastapi.staticfiles import StaticFiles
                    from fastapi.responses import FileResponse
                    from fastapi import HTTPException

                    @app.get("/{{path:path}}", include_in_schema=False)
                    def _spa(path: str = ""):
                        if path.startswith("api/"):
                            raise HTTPException(status_code=404, detail="Not found")
                        f = _DIST / path
                        return FileResponse(str(f) if f.is_file() else str(_DIST / "index.html"))

                if __name__ == "__main__":
                    import uvicorn
                    uvicorn.run(app, host="0.0.0.0", port=8000)
            """)
            run_preview_py.write_text(preview_content)

        # ── Patch models.py ────────────────────────────────────────────────────
        _models_py = backend_dir / "src" / "models.py"
        if _models_py.exists():
            import re as _re_m
            _m_src = _models_py.read_text()
            _m_lines = _m_src.splitlines()
            _m_out = []
            for _line in _m_lines:
                if "Column(" in _line:
                    _seen_kw: set = set()

                    def _drop_dup(m: "_re_m.Match") -> str:
                        k = m.group(1)
                        if k in _seen_kw:
                            return ""
                        _seen_kw.add(k)
                        return m.group(0)

                    _line = _re_m.sub(r",\s*(\w+)=[^,)]+", _drop_dup, _line)
                _m_out.append(_line)
            _m_fixed = "\n".join(_m_out)
            if _m_fixed != _m_src:
                _models_py.write_text(_m_fixed)

        if _models_py.exists():
            import re as _re_fk
            _fk_src = _models_py.read_text()
            _fk_lines = []
            for _ln in _fk_src.splitlines():
                if "ForeignKey" in _ln and "nullable=False" in _ln:
                    _ln = _ln.replace("nullable=False", "nullable=True")
                _fk_lines.append(_ln)
            _fk_fixed = "\n".join(_fk_lines)
            if _fk_fixed != _fk_src:
                _models_py.write_text(_fk_fixed)

        # ── Patch schemas.py ───────────────────────────────────────────────────
        _schemas_py = backend_dir / "src" / "schemas.py"
        if _schemas_py.exists():
            import re as _re_s
            _s_src = _schemas_py.read_text()
            _s_src = _re_s.sub(
                r"(\n    (?:created_by|workspace_id|org_id|agent_id|member_id"
                r"|organization_id|user_id)): int(?! =)",
                r"\1: Optional[int] = None",
                _s_src,
            )
            _s_src = _re_s.sub(r"(\n    is_active): bool(?! =)", r"\1: bool = True", _s_src)
            _s_src = _re_s.sub(r"(\n    temperature): float(?! =)", r"\1: float = 0.7", _s_src)
            _s_src = _re_s.sub(r"(\n    max_tokens): int(?! =)", r"\1: int = 4096", _s_src)
            _s_src = _re_s.sub(
                r"(\n    tools_json): str(?! =)", r"\1: Optional[str] = None", _s_src
            )
            _schemas_py.write_text(_s_src)

        # ── Patch crud.py ──────────────────────────────────────────────────────
        _crud_py = backend_dir / "src" / "routers" / "crud.py"
        if _crud_py.exists():
            import re as _re_c
            _c_src = _crud_py.read_text()
            _c_src = _c_src.replace(
                'getattr(current_user, "role", None)', 'current_user.get("role")'
            )
            _c_src = _c_src.replace(
                "getattr(current_user, 'role', None)", 'current_user.get("role")'
            )
            _c_src = _re_c.sub(
                r'    if current_user\.get\("role"\) not in \[.*?\]:\n        raise HTTPException\(status_code=403.*?\)\n',
                "",
                _c_src,
            )
            _crud_py.write_text(_c_src)

        # ── Patch main.py: add /api prefix for entity routers ─────────────────
        _main_py_crud = backend_dir / "src" / "main.py"
        if _main_py_crud.exists():
            _mp = _main_py_crud.read_text()
            if "for _router in all_routers:" in _mp and 'prefix="/api"' not in _mp:
                _mp = _mp.replace(
                    "    app.include_router(_router)",
                    '    app.include_router(_router, prefix="/api")',
                )
                _main_py_crud.write_text(_mp)

        # ── Patch react-router-dom → @tanstack/react-router ──────────────────
        _fe_src_dir = frontend_dir / "src" if frontend_dir else None
        if _fe_src_dir and _fe_src_dir.is_dir():
            for _tsx in _fe_src_dir.rglob("*.tsx"):
                _tsx_src = _tsx.read_text()
                if "react-router-dom" in _tsx_src:
                    _tsx_src = (
                        _tsx_src
                        .replace("from 'react-router-dom'", "from '@tanstack/react-router'")
                        .replace('from "react-router-dom"', 'from "@tanstack/react-router"')
                    )
                    _tsx.write_text(_tsx_src)

        # ── Patch auth.py: replace passlib with direct bcrypt ─────────────────
        _auth_py = backend_dir / "src" / "auth.py"
        if _auth_py.exists():
            _auth = _auth_py.read_text()
            if "AetherOS: bcrypt direct" not in _auth and "CryptContext" in _auth:
                _bcrypt_patch = (
                    "\n# AetherOS: bcrypt direct — passlib CryptContext incompatible with bcrypt >= 4.x\n"
                    "try:\n"
                    "    import bcrypt as _bcrypt_mod\n"
                    "    def get_password_hash(pw: str) -> str:\n"
                    "        return _bcrypt_mod.hashpw(pw.encode(), _bcrypt_mod.gensalt()).decode()\n"
                    "    def verify_password(plain: str, hashed: str) -> bool:\n"
                    "        try: return _bcrypt_mod.checkpw(plain.encode(), hashed.encode())\n"
                    "        except Exception: return False\n"
                    "except ImportError:\n"
                    "    pass  # fall back to passlib\n"
                )
                _auth_py.write_text(_auth + _bcrypt_patch)

        # ── Patch seed.py: enforce predictable demo password ──────────────────
        _PREVIEW_PASSWORD = "Admin1234!"
        _preview_email = "admin@example.com"
        _seed_py = backend_dir / "src" / "seed.py"
        if _seed_py.exists():
            import re as _re_seed
            _seed = _seed_py.read_text()
            _email_m = _re_seed.search(r'email\s*=\s*["\']([^"\']+@[^"\']+)["\']', _seed)
            if _email_m:
                _preview_email = _email_m.group(1)
            _seed_patched = _re_seed.sub(
                r'(_ADMIN_PASSWORD\s*=\s*)["\'][^"\']*["\']',
                f'\\1"{_PREVIEW_PASSWORD}"',
                _seed,
            )
            _seed_patched = _re_seed.sub(
                r"get_password_hash\s*\(\s*os\.environ\.get\s*\([^)]+\)\s*\)",
                f'get_password_hash("{_PREVIEW_PASSWORD}")',
                _seed_patched,
            )
            if _seed_patched != _seed:
                _seed_py.write_text(_seed_patched)

        _creds_path = root_dir / "preview_credentials.json"
        _creds_path.write_text(json.dumps({
            "email": _preview_email,
            "password": _PREVIEW_PASSWORD,
            "note": "Demo credentials for the AetherOS preview — change before production",
        }))
        with open(log_path, "a") as _lf:
            _lf.write(
                f"[AetherOS] Preview credentials: {_preview_email} / {_PREVIEW_PASSWORD}\n"
            )

        # ── Start uvicorn ──────────────────────────────────────────────────────
        _env = {**os.environ}
        _env["DATABASE_URL"] = f"sqlite+aiosqlite:///{root_dir}/preview.db"
        _env["PYTHONPATH"] = (
            str(backend_dir / "src") + ":" + _env.get("PYTHONPATH", "")
        )

        _alembic_ini = backend_dir / "alembic.ini"
        if _alembic_ini.exists():
            with open(log_path, "a") as _lf:
                _lf.write("[AetherOS] Running alembic upgrade head...\n")
            _alembic_result = _sp.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=str(backend_dir),
                capture_output=True,
                timeout=60,
                env=_env,
            )
            with open(log_path, "a") as _lf:
                if _alembic_result.returncode == 0:
                    _lf.write("[AetherOS] Alembic migrations applied successfully.\n")
                else:
                    _err = (_alembic_result.stderr or b"").decode(errors="replace")[-400:]
                    _lf.write(
                        f"[AetherOS] Alembic migration failed (falling back to create_all): {_err}\n"
                    )

        def _try_start_backend() -> Optional[_sp.Popen]:
            log_file = open(log_path, "a")
            log_file.write(
                f"[AetherOS] Starting generated backend on port {port} from {backend_dir}\n"
            )
            log_file.flush()
            proc = _sp.Popen(
                [sys.executable, "-m", "uvicorn", "src.main:app",
                 "--host", "127.0.0.1", "--port", str(port)],
                cwd=str(backend_dir),
                stdout=log_file,
                stderr=log_file,
                shell=False,
                env=_env,
                start_new_session=True,
            )
            if proc.poll() is not None:
                log_file.write("[AetherOS] Backend crashed — falling back to frontend-only server\n")
                log_file.flush()
                return None
            return proc

        def _start_frontend_server() -> _sp.Popen:
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
                log_file = open(log_path, "a")
                log_file.write("[AetherOS] Reusing existing custom preview stub\n")
                log_file.flush()
                return _sp.Popen(
                    [sys.executable, "-m", "uvicorn", "main:app",
                     "--host", "127.0.0.1", "--port", str(port)],
                    cwd=str(_stub_dir),
                    stdout=log_file,
                    stderr=log_file,
                    shell=False,
                    start_new_session=True,
                )
            _stub_main.write_text(self._stub_main_py(_dist_path))
            log_file = open(log_path, "a")
            log_file.write(
                f"[AetherOS] Starting frontend-only preview server on port {port}\n"
            )
            log_file.flush()
            return _sp.Popen(
                [sys.executable, "-m", "uvicorn", "main:app",
                 "--host", "127.0.0.1", "--port", str(port)],
                cwd=str(_stub_dir),
                stdout=log_file,
                stderr=log_file,
                shell=False,
                start_new_session=True,
            )

        try:
            proc = _try_start_backend()
            await asyncio.sleep(2)
            mode = "backend"
            if proc is None:
                if frontend_dist and frontend_dist.is_dir():
                    proc = _start_frontend_server()
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
            except Exception:
                pass

            import time as _ts_state
            _state_file = root_dir / "run_app_state.json"
            try:
                _state_file.write_text(json.dumps({
                    "run_id": run_id,
                    "port": port,
                    "pid": proc.pid,
                    "started_at": _ts_state.time(),
                    "mode": mode,
                }))
            except Exception:
                pass

            try:
                from aether_os.core.db_utils import async_update_run_live_url as _aulul
                await _aulul(run_id, "/app-preview/")
            except Exception:
                pass

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
                "live_url": "/app-preview/",
                "preview_url": "/app-preview/",
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start app: {e}")

    # ── Private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _api_explorer_html(project_label: str, run_id: str) -> str:
        return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{project_label}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;padding:2rem}}
  h1{{font-size:1.5rem;font-weight:700;color:#f1f5f9;margin-bottom:.25rem}}
  .badge{{display:inline-block;padding:.2rem .6rem;border-radius:9999px;font-size:.7rem;font-weight:600;background:#1e3a5f;color:#60a5fa;margin-bottom:1.5rem}}
  .card{{background:#1e293b;border:1px solid #334155;border-radius:.75rem;padding:1.25rem;margin-bottom:1rem}}
  .card h2{{font-size:.85rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.75rem}}
  .cred-row{{display:flex;gap:.5rem;align-items:center;margin-bottom:.4rem;font-size:.875rem}}
  .label{{color:#64748b;width:5rem;flex-shrink:0}}
  code{{background:#0f172a;color:#34d399;padding:.15rem .4rem;border-radius:.3rem;font-size:.8rem;font-family:monospace}}
  .btn{{display:inline-flex;align-items:center;gap:.4rem;padding:.5rem 1rem;border-radius:.5rem;font-size:.8rem;font-weight:600;text-decoration:none;transition:opacity .15s}}
  .btn-primary{{background:#6366f1;color:#fff}}.btn-primary:hover{{opacity:.85}}
  .btn-outline{{background:transparent;border:1px solid #334155;color:#94a3b8}}.btn-outline:hover{{color:#f1f5f9;border-color:#6366f1}}
  .btn-row{{display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.75rem}}
  #endpoints{{font-size:.8rem;line-height:1.8}}
  .method{{display:inline-block;width:3.5rem;text-align:center;border-radius:.25rem;padding:.05rem .3rem;font-size:.7rem;font-weight:700;margin-right:.4rem}}
  .GET{{background:#065f46;color:#6ee7b7}}.POST{{background:#1e3a5f;color:#93c5fd}}
  .PUT,.PATCH{{background:#44310a;color:#fcd34d}}.DELETE{{background:#4c1d24;color:#fca5a5}}
  #status{{margin-top:.5rem;font-size:.75rem;color:#64748b}}
</style>
</head>
<body>
<h1>{project_label}</h1>
<div class="badge">AetherOS Generated App · Preview Mode</div>

<div class="card">
  <h2>Demo Credentials</h2>
  <div class="cred-row"><span class="label">Email</span><code id="email">loading...</code></div>
  <div class="cred-row"><span class="label">Password</span><code id="password">loading...</code></div>
  <div class="btn-row">
    <a href="/app-preview/docs" target="_blank" class="btn btn-primary">API Docs (Swagger)</a>
    <a href="/app-preview/openapi.json" target="_blank" class="btn btn-outline">JSON Schema</a>
  </div>
</div>

<div class="card">
  <h2>API Endpoints</h2>
  <div id="endpoints"><span style="color:#475569">Loading...</span></div>
  <div id="status"></div>
</div>

<script>
const base='/app-preview';
fetch('/api/factory/runs/{run_id}/preview-credentials',{{headers:{{'Authorization':'Bearer '+(localStorage.getItem('aether_token')||'')}}}})
  .then(r=>r.ok?r.json():null).then(d=>{{
    if(d){{document.getElementById('email').textContent=d.email||'admin@example.com';document.getElementById('password').textContent=d.password||'Admin1234!';}}
  }}).catch(()=>{{}});

fetch(base+'/openapi.json').then(r=>r.json()).then(spec=>{{
  const paths=Object.entries(spec.paths||{{}});
  const html=paths.slice(0,40).flatMap(([path,methods])=>
    Object.entries(methods).filter(([m])=>['get','post','put','patch','delete'].includes(m)).map(([method,op])=>
      `<div><span class="method ${{method.toUpperCase()}}">${{method.toUpperCase()}}</span><code>${{path}}</code> <span style="color:#475569">${{op.summary||''}}</span></div>`
    )
  ).join('');
  document.getElementById('endpoints').innerHTML=html||'<span style="color:#475569">No endpoints found</span>';
  document.getElementById('status').textContent=`${{paths.length}} endpoint group(s) available`;
}}).catch(()=>{{document.getElementById('endpoints').textContent='Could not load API schema.';}});
</script>
</body></html>"""

    @staticmethod
    def _stub_main_py(dist_path: Optional[str]) -> str:
        dist_block = ""
        if dist_path:
            dist_block = f"""
_DIST = pathlib.Path(r"{dist_path}")
if _DIST.is_dir():
    @app.get("/{{path:path}}", include_in_schema=False)
    def spa(path: str = ""):
        f = _DIST / path
        if f.is_file() and not f.name.endswith(".html"):
            return FileResponse(str(f))
        html_path = f if (f.is_file() and f.name.endswith(".html")) else _DIST / "index.html"
        html = html_path.read_text(encoding="utf-8")
        if "<body" in html and "_aether_crash_banner" not in html:
            html = html.replace("<body", _BANNER_SCRIPT + "<body", 1)
        return HTMLResponse(html)
"""
        return f"""from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
import os, secrets, pathlib, re

app = FastAPI()

_PREVIEW_TOKEN = os.environ.get("PREVIEW_TOKEN", secrets.token_hex(32))
_MOCK_USER = {{"id": 1, "email": "admin@example.com", "name": "Admin User", "role": "admin"}}

_BANNER_SCRIPT = \"\"\"
<style>
  #__aether_crash_banner {{
    position: fixed; top: 0; left: 0; right: 0; z-index: 99999;
    background: #dc2626; color: #fff; font-family: monospace; font-size: 13px;
    padding: 8px 16px; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,.4);
  }}
  #__aether_crash_banner a {{ color: #fef08a; text-decoration: underline; }}
</style>
<div id="__aether_crash_banner">
  Backend failed to start. All API calls return empty data.
</div>
\"\"\"

@app.post("/api/auth/login")
@app.post("/api/v1/auth/login")
async def mock_login(request: Request):
    return JSONResponse({{"access_token": _PREVIEW_TOKEN, "token_type": "bearer", "user": _MOCK_USER}})

@app.get("/api/auth/me")
@app.get("/api/v1/auth/me")
async def mock_me():
    return JSONResponse(_MOCK_USER)

@app.post("/api/auth/logout")
async def mock_logout():
    return JSONResponse({{"success": True}})

@app.get("/api/{{path:path}}")
async def mock_api_get(path: str):
    return JSONResponse({{"items": [], "total": 0, "_preview_mode": True,
                          "_error": "Backend crashed — data unavailable"}})

@app.post("/api/{{path:path}}")
async def mock_api_post(path: str, request: Request):
    return JSONResponse({{"success": False, "_preview_mode": True,
                          "_error": "Backend crashed — write operations disabled"}}, status_code=503)

@app.put("/api/{{path:path}}")
async def mock_api_put(path: str, request: Request):
    return JSONResponse({{"success": False, "_preview_mode": True,
                          "_error": "Backend crashed — write operations disabled"}}, status_code=503)

@app.delete("/api/{{path:path}}")
async def mock_api_delete(path: str):
    return JSONResponse({{"success": False, "_preview_mode": True,
                          "_error": "Backend crashed — delete operations disabled"}}, status_code=503)
{dist_block}
"""
