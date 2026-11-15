"""KAN-97: no constant admin password anywhere the pipeline writes or runs generated apps."""
import json
import pathlib

from aether_os.core.run_app.process_manager_helpers import patch_generated_project

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _patch(tmp_path):
    root = tmp_path / "projects" / "run1"
    backend = root / "p04_backend" / "backend_codegen" / "app"
    (backend / "src").mkdir(parents=True)
    (backend / "src" / "seed.py").write_text('ADMIN = dict(email="boss@acme.io")\n')
    return root, backend, patch_generated_project(
        backend_dir=backend, root_dir=root, frontend_dir=None, frontend_dist=None, log_path=tmp_path / "p.log")


def test_preview_password_is_random_per_run_and_stable_across_relaunch(tmp_path):
    root, backend, (email, pw) = _patch(tmp_path)
    assert email == "boss@acme.io" and len(pw) >= 16 and "1234" not in pw
    assert json.loads((root / "preview_credentials.json").read_text())["password"] == pw
    again = patch_generated_project(backend_dir=backend, root_dir=root, frontend_dir=None,
                                    frontend_dist=None, log_path=tmp_path / "p.log")
    assert again[1] == pw
    assert _patch(tmp_path / "other")[2][1] != pw


def test_no_constant_admin_password_in_pipeline_source():
    bad = [str(p.relative_to(ROOT)) for d in ("core", "phases", "stages", "gateway", "orchestrator")
           for p in (ROOT / d).rglob("*.py") if "Admin1234" in p.read_text(errors="replace")]
    assert not bad, bad
