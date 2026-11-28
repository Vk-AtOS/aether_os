"""KAN-270: s11 no longer writes its own 87 MB delivery zip (node_modules, .env, key, served by nothing).

It runs the clean export (the same one the download and the GitHub push use) and records its manifest.
"""
import asyncio
import json
from types import SimpleNamespace

from aether_os.stages.s11_handoff.supervisor import HandoffStageSupervisor


def _w(root, rel, text="x"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _ws(tmp_path):
    ws = tmp_path / "run"
    _w(ws, "p04_backend/backend_codegen/src/main.py", "app = 1")
    _w(ws, "p04_backend/backend_codegen/requirements.txt", "fastapi\n")
    _w(ws, "p04_backend/backend_codegen/.env", "SECRET_KEY=abcdefabcdefabcdef")
    _w(ws, "frontend/package.json", "{}")
    _w(ws, "frontend/node_modules/x/index.js", "x")
    _w(ws, "p10_docs_delivery/docs/README.md", "# docs")
    return ws


def test_s11_verifies_the_clean_export_and_writes_no_zip(tmp_path):
    ws, out, issues = _ws(tmp_path), tmp_path / "out", []
    out.mkdir()
    pi = SimpleNamespace(project_id="p", input_data={"project_dir": str(ws), "project_name": "App"})
    path = asyncio.run(HandoffStageSupervisor()._check_export(pi, out, issues))
    manifest = json.loads(path.read_text())
    paths = {f["path"] for f in manifest["files"]}
    assert not issues and {"backend/src/main.py", "frontend/package.json", "docs/README.md"} <= paths
    assert not any("node_modules" in p or p.endswith(".env") for p in paths)
    assert not list(out.glob("*.zip")) and not hasattr(HandoffStageSupervisor, "_build_project_zip")


def test_s11_flags_a_run_that_cannot_be_exported(tmp_path):
    ws, out, issues = _ws(tmp_path), tmp_path / "out", []
    out.mkdir()
    _w(ws, "p04_backend/backend_codegen/src/leak.py", "K='''-----BEGIN RSA PRIVATE KEY-----'''")
    pi = SimpleNamespace(project_id="p", input_data={"project_dir": str(ws)})
    assert asyncio.run(HandoffStageSupervisor()._check_export(pi, out, issues)) is None
    assert issues and "private-key" in issues[0]
