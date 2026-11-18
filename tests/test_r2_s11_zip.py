"""KAN-100: the delivery ZIP carries the docs, portal and handoff package, not only backend and frontend."""
import zipfile
from types import SimpleNamespace

from aether_os.phases.base import TaskResult
from aether_os.stages.s11_handoff.supervisor import HandoffStageSupervisor


def _res(path):
    return TaskResult(output_path=str(path), confidence=1.0, success=True)


def test_zip_contains_docs_portal_and_handoff(tmp_path):
    be, fe = tmp_path / "backend", tmp_path / "frontend"
    docs, portal, handoff = tmp_path / "p10", tmp_path / "p14", tmp_path / "p15"
    for d, name in ((be, "main.py"), (fe, "App.tsx"), (docs, "README.md"), (portal, "index.html"), (handoff, "postman/collection.json")):
        f = d / name
        f.parent.mkdir(parents=True)
        f.write_text("x")
    docs_summary = docs / "docs_summary.json"          # p10 returns its summary FILE as output_path
    docs_summary.write_text("{}")
    out = tmp_path / "out"
    out.mkdir()
    pi = SimpleNamespace(input_data={"backend_output_path": str(be), "frontend_output_path": str(fe)})
    zp = HandoffStageSupervisor()._build_project_zip(
        pi, out, [], {"docs": _res(docs_summary), "client_portal": _res(portal), "handoff": _res(handoff), "none": None})
    names = set(zipfile.ZipFile(zp).namelist())
    assert {"backend/main.py", "frontend/App.tsx", "docs/README.md", "client_portal/index.html",
            "handoff/postman/collection.json"} <= names
