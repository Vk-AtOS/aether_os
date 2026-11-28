"""KAN-268 / KAN-271 D6: the clean export of a run workspace is complete, holds no secret, and its CI is runnable."""
import json
import zipfile
from pathlib import Path

import pytest
import yaml

from aether_os.core import project_export as pe

REAL_SECRET = "9be31cca04909bc35366057cf7cd3812f66ee137573518a8662a517376facb13"
PEM = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n-----END PRIVATE KEY-----\n"

PREVIEW_BLOCK = '''

# AetherOS: serve the Vite-built frontend for all non-API paths (including root)
import pathlib as _spa_pathlib
_FRONTEND_DIST = _spa_pathlib.Path(r"/Users/someone/.aether_os/projects/abc/p05_frontend/frontend/dist")

def _spa_index():
    return None

@app.get("/{path:path}", include_in_schema=False)
def _spa_catchall(path: str = ""):
    return _spa_index()
'''


def _w(root: Path, rel: str, text: str = "x") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


@pytest.fixture
def ws(tmp_path):
    """The messy layout of a real run: stage folders, copies of src, keys, .env, node_modules, preview state."""
    w = tmp_path / "run"
    be = "p04_backend/backend_codegen"
    _w(w, f"{be}/src/main.py", 'from fastapi import FastAPI\napp = FastAPI()\n@app.get("/health")\ndef health():\n    return {"ok": 1}\n' + PREVIEW_BLOCK)
    _w(w, f"{be}/src/__init__.py", "")
    _w(w, f"{be}/src/__pycache__/main.cpython-311.pyc", "bin")
    _w(w, f"{be}/src/app.db", "sqlite")
    _w(w, f"{be}/src/.env", f"SECRET_KEY={REAL_SECRET}\nADMIN_PASSWORD=Admin1234!\n")
    _w(w, f"{be}/.env", f"SECRET_KEY={REAL_SECRET}\n")
    _w(w, f"{be}/.env.example", f"DATABASE_URL=sqlite+aiosqlite:///./app.db\nSECRET_KEY={REAL_SECRET}\nADMIN_PASSWORD=Admin1234!\nCORS_ORIGINS=http://localhost:3000\n")
    _w(w, f"{be}/private_key.pem", PEM)
    _w(w, f"{be}/requirements.txt", "fastapi>=0.111\nuvicorn>=0.29\nasyncpg>=0.29\nsqlalchemy>=2\n")
    _w(w, f"{be}/Dockerfile", "FROM python:3.11\nCOPY requirements.txt* ./\n")
    _w(w, f"{be}/alembic/env.py", "# alembic")
    _w(w, f"{be}/tests/test_health.py", "def test_ok():\n    assert True\n")
    fe = "frontend"
    _w(w, f"{fe}/package.json", json.dumps({"name": "fe", "scripts": {"build": "vite build", "lint": "eslint ."}}))
    _w(w, f"{fe}/package-lock.json", "{}")
    _w(w, f"{fe}/vite.config.ts", "export default defineConfig({\n  base: '/app-preview/',\n  plugins: [react()],\n  server: {\n    proxy: {\n      '/app-preview/api': {\n        target: 'http://localhost:8000',\n        rewrite: (path: string) => path.replace(/^\\/app-preview\\/api/, ''),\n      },\n      '/api': {\n        target: 'http://localhost:8000',\n      },\n    }\n  }\n})\n")
    _w(w, f"{fe}/src/App.tsx", "export const router = createRouter({ routeTree, basepath: '/app-preview' })\n")
    _w(w, f"{fe}/src/lib/api.ts", "export const apiClient = axios.create({ baseURL: '/app-preview/api' })\n")
    _w(w, f"{fe}/node_modules/react/index.js", "module.exports={}")
    _w(w, f"{fe}/dist/index.html", "<html></html>")
    _w(w, f"{fe}/.env.production", "VITE_API_URL=/app-preview\n")
    _w(w, f"{fe}/gate_result.json", "{}")
    _w(w, "p05_frontend/frontend/package.json", json.dumps({"name": "draft", "scripts": {}}))
    _w(w, "p05_frontend/frontend/src/App.tsx", "draft")
    _w(w, "p03_scaffolding/Smoke/src/main.py", "scaffold copy")
    _w(w, "p03_scaffolding/Smoke/requirements.txt", "fastapi")
    _w(w, "p08_cicd_deployment/cicd/ci.yml", "name: CI")
    _w(w, ".github/workflows/ci.yml", "name: old\njobs:\n  b:\n    runs-on: x\n    steps:\n      - run: pip install -r requirements.txt\n")
    _w(w, "private_key.pem", PEM)
    _w(w, "preview_credentials.json", '{"email":"a@b.c","password":"hunter2hunter2"}')
    _w(w, "run_app.log", "log")
    _w(w, "run_preview.py", "preview")
    _w(w, "p10_docs_delivery/docs/API.md", "# API")
    _w(w, "p10_docs_delivery/docs/.env", "TOKEN=abc")
    _w(w, "p15_handoff/postman_collection.json", "{}")
    return w


def _names(root: Path):
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def export(ws, tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    manifest = pe.assemble_export(ws, dest, "My App")
    return dest, manifest


def test_export_is_clean(export):
    dest, manifest = export
    names = _names(dest)
    banned_suffix = (".pem", ".db", ".log", ".pyc")
    assert not [n for n in names if n.endswith(banned_suffix)]
    assert not [n for n in names if Path(n).name in (".env", "preview_credentials.json", "run_preview.py", "gate_result.json")]
    assert not [n for n in names if n.split("/")[0][:1] in ("p", "s") and n.split("/")[0][1:3].isdigit()]
    assert not [n for n in names if "node_modules" in n or "/dist/" in n or n.startswith("frontend/.env")]
    assert pe.scan_tree(dest) == []
    for n in names:
        assert REAL_SECRET not in (dest / n).read_text(errors="ignore"), n
    assert manifest["excluded"]["secret"] >= 4 and manifest["layout"]["frontend"] == "frontend"


def test_export_is_complete(export):
    dest, manifest = export
    names = _names(dest)
    assert {"backend/src/main.py", "backend/requirements.txt", "backend/Dockerfile", "backend/alembic/env.py",
            "backend/tests/test_health.py", "frontend/package.json", "frontend/package-lock.json",
            "frontend/src/App.tsx", "frontend/Dockerfile", "frontend/nginx.conf", "docker-compose.yml",
            ".env.example", "README.md", ".github/workflows/ci.yml", "MANIFEST.json",
            "docs/API.md", "handoff/postman_collection.json"} <= names
    assert "frontend/src/App.tsx" in names and (dest / "frontend/src/App.tsx").read_text().startswith("export const router")
    assert "draft" not in (dest / "frontend/src/App.tsx").read_text()          # the repaired frontend, not the p05 draft
    listed = {f["path"] for f in manifest["files"]}
    assert listed == names - {"MANIFEST.json"} and all(len(f["sha256"]) == 64 for f in manifest["files"])
    assert json.loads((dest / "MANIFEST.json").read_text())["file_count"] == manifest["file_count"]


def test_preview_only_rewrites_are_removed(export):
    dest, manifest = export
    main = (dest / "backend/src/main.py").read_text()
    assert "_FRONTEND_DIST" not in main and "/Users/" not in main and "def health" in main
    vite = (dest / "frontend/vite.config.ts").read_text()
    assert "app-preview" not in vite and "plugins: [react()]" in vite and "'/api'" in vite
    assert "basepath" not in (dest / "frontend/src/App.tsx").read_text()
    assert "baseURL: '/api'" in (dest / "frontend/src/lib/api.ts").read_text()
    assert {"backend/src/main.py", "frontend/vite.config.ts", "frontend/src/App.tsx", "frontend/src/lib/api.ts"} <= set(manifest["rewritten"])


def test_generated_files_are_deployable_and_use_placeholders(export):
    dest, _ = export
    env = (dest / ".env.example").read_text()
    assert "SECRET_KEY=CHANGE_ME" in env and "ADMIN_PASSWORD=CHANGE_ME" in env and "POSTGRES_PASSWORD=CHANGE_ME" in env
    assert "CORS_ORIGINS=http://localhost:3000" in env
    dc = yaml.safe_load((dest / "docker-compose.yml").read_text())
    assert set(dc["services"]) == {"db", "backend", "frontend"}
    be = dc["services"]["backend"]
    assert be["build"] == "./backend" and (dest / "backend/Dockerfile").exists()
    assert be["environment"]["SECRET_KEY"].startswith("${SECRET_KEY:?")
    assert be["environment"]["ADMIN_PASSWORD"].startswith("${ADMIN_PASSWORD:?")
    assert dc["services"]["frontend"]["build"] == "./frontend"
    assert 'CMD ["uvicorn", "src.main:app"' in (dest / "backend/Dockerfile").read_text()
    assert "proxy_pass http://backend:8000;" in (dest / "frontend/nginx.conf").read_text()    # /api kept, not stripped
    assert "deploy" in (dest / "README.md").read_text().lower() and "cp .env.example .env" in (dest / "README.md").read_text()


def test_ci_workflow_references_only_paths_that_exist(export):
    dest, _ = export
    wf = yaml.safe_load((dest / ".github/workflows/ci.yml").read_text())
    assert set(wf["jobs"]) == {"backend", "frontend", "docker"}
    assert pe.workflow_path_problems(dest) == []
    text = (dest / ".github/workflows/ci.yml").read_text()
    assert "working-directory: backend" in text and "pytest tests" in text and "npm ci" in text


def test_validator_catches_the_old_flat_workflow(export):
    """The p08 workflow (root requirements.txt, scripts/, frontend) points at paths the export does not have."""
    dest, _ = export
    (dest / ".github/workflows/ci.yml").write_text(
        "name: CI\non: push\njobs:\n  backend:\n    runs-on: x\n    steps:\n"
        "      - run: pip install -r requirements.txt\n      - run: pytest tests/ -v\n"
        "  compliance:\n    runs-on: x\n    steps:\n      - uses: actions/setup-python@v5\n        with:\n          cache-dependency-path: requirements.txt\n"
        "      - run: docker build -t x .\n")
    problems = pe.workflow_path_problems(dest)
    assert any("requirements.txt" in p for p in problems) and any("tests/" in p for p in problems)


def test_export_refuses_a_private_key_in_source_without_leaking_it(ws, tmp_path):
    _w(ws, "p04_backend/backend_codegen/src/keys.py", f'KEY = """{PEM}"""\n')
    dest = tmp_path / "o"
    dest.mkdir()
    with pytest.raises(pe.ExportError) as e:
        pe.assemble_export(ws, dest, "x")
    assert any(f.rule == "private-key" and f.path == "backend/src/keys.py" for f in e.value.findings)
    assert "MIIEvQ" not in str(e.value)


def test_export_refuses_preview_host_path_left_in_source(ws, tmp_path):
    _w(ws, "p04_backend/backend_codegen/src/cfg.py", 'DIST = "/Users/apple/.aether_os/projects/x/dist"\n')
    dest = tmp_path / "o"
    dest.mkdir()
    with pytest.raises(pe.ExportError) as e:
        pe.assemble_export(ws, dest, "x")
    assert any(f.rule == "preview-host-path" for f in e.value.findings)


def test_scan_flags_secret_files_and_password_values(tmp_path):
    _w(tmp_path, ".env", "A=1")
    _w(tmp_path, "id_rsa", "k")
    _w(tmp_path, "p03_scaffolding/x.txt", "x")
    _w(tmp_path, "cfg/settings.yml", "db:\n  password: hunter2hunter2\nok:\n  password: ${DB_PASSWORD}\n")
    _w(tmp_path, "docker-compose.yml", "environment:\n  DATABASE_URL: postgresql://app:realpw@db/app\n  TOKEN_EXPIRE_MINUTES: 30\n")
    rules = {(f.path, f.rule) for f in pe.scan_tree(tmp_path)}
    assert (".env", "secret-or-state-file") in rules and ("id_rsa", "secret-or-state-file") in rules
    assert ("p03_scaffolding", "pipeline-folder") in rules
    assert ("cfg/settings.yml", "password-like-value") in rules
    assert ("docker-compose.yml", "credentials-in-url") in rules
    assert ("docker-compose.yml", "password-like-value") not in rules


def test_symlinked_secret_is_not_followed(ws, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("TOP SECRET OUTSIDE")
    (ws / "p04_backend/backend_codegen/src/notes.txt").symlink_to(outside)
    dest = tmp_path / "o"
    dest.mkdir()
    pe.assemble_export(ws, dest, "x")
    assert not any("TOP SECRET OUTSIDE" in (dest / n).read_text(errors="ignore") for n in _names(dest))


def test_no_backend_or_no_requirements_fails_loudly(tmp_path):
    w = tmp_path / "empty"
    w.mkdir()
    with pytest.raises(pe.ExportError, match="no backend"):
        pe.assemble_export(w, tmp_path / "o1")
    _w(w, "p04_backend/backend_codegen/src/main.py", "app = 1")
    with pytest.raises(pe.ExportError, match="requirements.txt"):
        pe.assemble_export(w, tmp_path / "o2")


def test_backend_only_run_and_sqlite_when_no_asyncpg(tmp_path):
    w = tmp_path / "w"
    _w(w, "p04_backend/backend_codegen/src/main.py", "app = 1")
    _w(w, "p04_backend/backend_codegen/requirements.txt", "fastapi\naiosqlite\n")
    dest = tmp_path / "o"
    dest.mkdir()
    m = pe.assemble_export(w, dest, "api")
    dc = yaml.safe_load((dest / "docker-compose.yml").read_text())
    assert set(dc["services"]) == {"backend"} and "frontend" not in set(_names(dest)) and m["layout"]["database"] == "sqlite"
    assert set(yaml.safe_load((dest / ".github/workflows/ci.yml").read_text())["jobs"]) == {"backend", "docker"}
    assert pe.workflow_path_problems(dest) == []


def test_zip_is_the_export_and_small(ws):
    buf, manifest = pe.build_export_zip(ws, "My App")
    names = set(zipfile.ZipFile(buf).namelist())
    assert len(names) == manifest["file_count"] + 1 < 60
    assert "backend/src/main.py" in names and not any(n.endswith(".pem") for n in names)


def test_download_endpoint_serves_the_clean_export(ws, tmp_path, monkeypatch):
    import asyncio
    from aether_os.gateway.routers import run_deploy_router as r
    home = tmp_path / "home"
    (home / ".aether_os/projects").mkdir(parents=True)
    ws.rename(home / ".aether_os/projects/run1")
    monkeypatch.setenv("HOME", str(home))

    class _Res:
        def scalar_one_or_none(self):
            return type("R", (), {"project_name": "My App"})()

    class _Sess:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, *_a):
            return _Res()

    monkeypatch.setattr(r, "get_session_factory", lambda: (lambda: _Sess()))

    async def go():
        resp = await r.download_run_zip("run1", {"org_id": "o"})
        return b"".join([c async for c in resp.body_iterator])

    data = asyncio.run(go())
    import io
    names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
    assert "backend/src/main.py" in names and "MANIFEST.json" in names
    assert not [n for n in names if n.endswith(".pem") or "node_modules" in n or n.startswith("p0")]


def test_unparseable_backend_file_is_a_warning_not_a_failure(ws, tmp_path):
    _w(ws, "p04_backend/backend_codegen/src/broken.py", "def (:\n")
    dest = tmp_path / "o"
    dest.mkdir()
    m = pe.assemble_export(ws, dest, "x")
    assert any(w.startswith("backend/src/broken.py:1") for w in m["warnings"])
