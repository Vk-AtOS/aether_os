"""KAN-195: previews get a random password per run, never a shared literal; it is not logged."""
import json

from aether_os.core.run_app.process_manager_helpers import patch_generated_project


def _project(tmp_path):
    (tmp_path / "backend" / "src").mkdir(parents=True)
    (tmp_path / "backend" / "src" / "seed.py").write_text(
        'import os\nemail = "owner@example.org"\n'
        'h = get_password_hash(os.environ.get("ADMIN_PASSWORD", "x"))\n')
    return tmp_path


def test_preview_password_is_random_and_not_logged(tmp_path):
    out = []
    for n in range(2):
        root = _project(tmp_path / str(n))
        log = root / "log.txt"
        email, pw = patch_generated_project(root / "backend", root, None, None, log)
        assert email == "owner@example.org" and len(pw) >= 12 and pw != "Admin1234!"
        assert pw not in log.read_text()
        assert json.loads((root / "preview_credentials.json").read_text())["password"] == pw
        assert pw in (root / "backend" / "src" / "seed.py").read_text()
        out.append(pw)
    assert out[0] != out[1]
