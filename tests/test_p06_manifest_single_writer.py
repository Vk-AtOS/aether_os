"""KAN-131: p06 writes the compliance manifest through the one hardened writer (core/compliance/manifest_writer):
it used to keep its own copy that followed symlinks inside the run directory, while the hardened one had no caller."""
import hashlib
import json
from types import SimpleNamespace

from aether_os.phases.p06_review_security import subtasks
from aether_os.phases.p06_review_security.manifest import write_compliance_manifest
from aether_os.phases.p08_cicd.generators import _generate_compliance_checker

ROUTE = "from fastapi import APIRouter\nrouter = APIRouter()\n\n@router.get('/items')\ndef items():\n    return []\n"


def _scan():
    route = SimpleNamespace(method="GET", path="/items", has_auth=True, has_audit_log=False,
                            has_input_validation=True, has_rate_limit=False)
    finding = SimpleNamespace(routes_affected=["GET /items"], rule_id="R1", rule_name="auth", severity="pass",
                              remediation="")
    return SimpleNamespace(routes=[route], findings=[finding], score=80, scanned_file="/x/src/main.py")


def _project(tmp_path):
    proj = tmp_path / "proj"
    (proj / "src" / "routers").mkdir(parents=True)
    (proj / "src" / "main.py").write_text(ROUTE)
    (proj / "src" / "routers" / "a.py").write_text(ROUTE.replace("items", "a"))
    return proj


def test_p06_uses_the_core_writer():
    assert subtasks.write_compliance_manifest is write_compliance_manifest
    assert write_compliance_manifest.__globals__["write_manifest_for_scan"].__module__ == \
        "aether_os.core.compliance.manifest_writer"


def test_manifest_content_and_the_generated_ci_check_agree(tmp_path):
    proj = _project(tmp_path)
    path = write_compliance_manifest(_scan(), proj, "App", "fintech")
    manifest = json.loads(path.read_text())
    assert manifest["overall_score"] == 80 and manifest["project_name"] == "App" and manifest["domain"] == "fintech"
    assert manifest["components"][0]["route"] == "GET /items" and manifest["components"][0]["file"] == "main.py"
    assert manifest["components"][0]["rules_satisfied"] == [{"id": "R1", "name": "auth"}]
    # the drift check that ships in the generated project recomputes the same fingerprint
    _generate_compliance_checker(proj, {})
    checker = proj / "scripts" / "check_compliance.py"
    src = checker.read_text()
    ns = {"__name__": "checker", "__file__": str(checker)}
    exec(compile(src, str(checker), "exec"), ns)
    assert ns["compute_fingerprint"](proj) == manifest["drift_fingerprint"] != hashlib.sha256(b"").hexdigest()


def test_fingerprint_does_not_read_through_a_link(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("@router.get('/secret')\ndef s(): pass\n")
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "main.py").write_text("x = 1\n")
    (proj / "src" / "r.py").symlink_to(outside / "secret.py")
    path = write_compliance_manifest(_scan(), proj, "App", "general")
    assert json.loads(path.read_text())["drift_fingerprint"] == hashlib.sha256(b"").hexdigest()


def test_manifest_is_not_written_through_a_planted_link(tmp_path):
    proj = _project(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    (proj / "compliance_manifest.json").symlink_to(victim)
    assert write_compliance_manifest(_scan(), proj, "App", "general") is None
    assert victim.read_text() == "keep me"
