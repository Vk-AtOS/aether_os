"""KAN-98 item 8: electron bundles a real backend, CLI config works, one keyring service per CLI."""
import asyncio
import subprocess
import sys
from types import SimpleNamespace

from aether_os.phases.p05c_desktop import task_agent as p05c
from aether_os.phases.p05d_cli.cli_generator import gen_config_py


def test_electron_builder_packages_a_backend_that_exists(tmp_path):
    backend = tmp_path / "be"
    (backend / "__pycache__").mkdir(parents=True)
    (backend / "main.py").write_text("app = 1\n")
    (backend / ".env").write_text("SECRET=1\n")
    out = tmp_path / "out"
    pi = SimpleNamespace(input_data={"build_profile": {"frontend_framework": "electron"},
                                     "backend_src_dir": str(backend), "project_name": "Acme Desk"})
    res = asyncio.run(p05c.run(pi, [], out))
    assert res.success
    desk = out / "desktop"
    assert (desk / "backend" / "main.py").is_file() and not (desk / "backend" / ".env").exists()
    yml = (desk / "electron-builder.yml").read_text()
    assert "from: backend" in yml and "../backend" not in yml


def test_electron_without_backend_fails_instead_of_shipping_an_unbootable_app(tmp_path):
    pi = SimpleNamespace(input_data={"build_profile": {"frontend_framework": "electron"}})
    assert asyncio.run(p05c.run(pi, [], tmp_path / "o")).success is False


def test_cli_config_defines_logger_and_per_project_service():
    code = gen_config_py("Acme CRM")
    assert 'SERVICE = "aetheros-acme-crm"' in code and "logger = logging.getLogger" in code
    assert gen_config_py("Other App") != code
    # reset_config must not NameError (keyring is stubbed to fail on delete)
    stub = "import sys,types;k=types.ModuleType('keyring');\n" \
           "def d(*a): raise RuntimeError('x')\nk.delete_password=d;sys.modules['keyring']=k\n"
    r = subprocess.run([sys.executable, "-c", stub + code + "\nreset_config()\nprint('ok')"],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr
