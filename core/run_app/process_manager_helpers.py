"""
AetherOS — RunAppManager Helpers
=================================
Static HTML/stub generators and code-patching utilities extracted from
RunAppManager to keep process_manager.py under the 600-line limit.
"""
from __future__ import annotations

import json
import logging
import pathlib
import re
import textwrap
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def api_explorer_html(project_label: str, run_id: str) -> str:
    """Generate the API-explorer fallback HTML page shown when Vite build fails."""
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


def stub_main_py(dist_path: Optional[str]) -> str:
    """Generate the stub FastAPI app used when the generated backend crashes."""
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


def patch_generated_project(
    backend_dir: pathlib.Path,
    root_dir: pathlib.Path,
    frontend_dir: Optional[pathlib.Path],
    frontend_dist: Optional[pathlib.Path],
    log_path: pathlib.Path,
) -> Tuple[str, str]:
    """
    Apply all AetherOS compatibility patches to a generated project.

    Patches: main.py, models.py, schemas.py, crud.py, auth.py, seed.py,
    react-router-dom imports, and writes run_preview.py.

    Returns (preview_email, preview_password).
    """
    _PREVIEW_PASSWORD = "Admin1234!"
    _preview_email = "admin@example.com"

    # ── Patch main.py ──────────────────────────────────────────────────────
    main_py = backend_dir / "src" / "main.py"
    if main_py.exists():
        content = main_py.read_text()
        content = content.replace("class_=typing.AsyncSession", "class_=AsyncSession")

        if re.search(r"^import timezone\b", content, re.MULTILINE):
            content = re.sub(
                r"^import timezone\b[^\n]*\n?", "", content, flags=re.MULTILINE
            )
            if "from datetime import" in content:
                content = re.sub(
                    r"from datetime import ([^\n]+)",
                    lambda m: m.group(0)
                    if "timezone" in m.group(1)
                    else m.group(0).rstrip() + ", timezone",
                    content,
                    count=1,
                )
            else:
                content = "from datetime import timezone\n" + content

        _sa_import_line = re.search(
            r"^from sqlalchemy import ([^\n]+)", content, re.MULTILINE
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
            content = re.sub(
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
            if not re.search(r'@app\.get\(["\']\/["\']', content):
                content += (
                    '\n\n@app.get("/", include_in_schema=False)\n'
                    "def _root_redirect():\n"
                    "    from fastapi.responses import RedirectResponse\n"
                    '    return RedirectResponse(url="/docs")\n'
                )

        if re.search(r"^@app\.", content, re.MULTILINE) and not re.search(
            r"^(?:app|application)\s*=\s*FastAPI\s*\(", content, re.MULTILINE
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

        # Write run_preview.py helper
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
        _m_src = _models_py.read_text()
        _m_lines = _m_src.splitlines()
        _m_out = []
        for _line in _m_lines:
            if "Column(" in _line:
                _seen_kw: set = set()

                def _drop_dup(m: re.Match) -> str:
                    k = m.group(1)
                    if k in _seen_kw:
                        return ""
                    _seen_kw.add(k)
                    return m.group(0)

                _line = re.sub(r",\s*(\w+)=[^,)]+", _drop_dup, _line)
            _m_out.append(_line)
        _m_fixed = "\n".join(_m_out)
        if _m_fixed != _m_src:
            _models_py.write_text(_m_fixed)

        # Fix ForeignKey nullable
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
        _s_src = _schemas_py.read_text()
        _s_src = re.sub(
            r"(\n    (?:created_by|workspace_id|org_id|agent_id|member_id"
            r"|organization_id|user_id)): int(?! =)",
            r"\1: Optional[int] = None",
            _s_src,
        )
        _s_src = re.sub(r"(\n    is_active): bool(?! =)", r"\1: bool = True", _s_src)
        _s_src = re.sub(r"(\n    temperature): float(?! =)", r"\1: float = 0.7", _s_src)
        _s_src = re.sub(r"(\n    max_tokens): int(?! =)", r"\1: int = 4096", _s_src)
        _s_src = re.sub(
            r"(\n    tools_json): str(?! =)", r"\1: Optional[str] = None", _s_src
        )
        _schemas_py.write_text(_s_src)

    # ── Patch crud.py ──────────────────────────────────────────────────────
    _crud_py = backend_dir / "src" / "routers" / "crud.py"
    if _crud_py.exists():
        _c_src = _crud_py.read_text()
        _c_src = _c_src.replace(
            'getattr(current_user, "role", None)', 'current_user.get("role")'
        )
        _c_src = _c_src.replace(
            "getattr(current_user, 'role', None)", 'current_user.get("role")'
        )
        _c_src = re.sub(
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
    _seed_py = backend_dir / "src" / "seed.py"
    if _seed_py.exists():
        _seed = _seed_py.read_text()
        _email_m = re.search(r'email\s*=\s*["\']([^"\']+@[^"\']+)["\']', _seed)
        if _email_m:
            _preview_email = _email_m.group(1)
        _seed_patched = re.sub(
            r'(_ADMIN_PASSWORD\s*=\s*)["\'][^"\']*["\']',
            f'\\1"{_PREVIEW_PASSWORD}"',
            _seed,
        )
        _seed_patched = re.sub(
            r"get_password_hash\s*\(\s*os\.environ\.get\s*\([^)]+\)\s*\)",
            f'get_password_hash("{_PREVIEW_PASSWORD}")',
            _seed_patched,
        )
        if _seed_patched != _seed:
            _seed_py.write_text(_seed_patched)

    # Write credentials file
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

    return _preview_email, _PREVIEW_PASSWORD
