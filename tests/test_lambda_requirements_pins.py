"""KAN-205: generated Lambda apps must not pin older releases than the audited lock, and every install path uses the lock."""
import re
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

from aether_os.phases.p05e_serverless.lambda_generator import gen_lambda_requirements

ROOT = Path(__file__).resolve().parents[1]


def _norm(name):
    return name.lower().replace("_", "-")


def _lock():
    out = {}
    for ln in (ROOT / "requirements.lock").read_text().splitlines():
        ln = ln.split("#")[0].strip()
        if ln and not ln.startswith("-"):
            r = Requirement(ln)
            out[_norm(r.name)] = Version(next(iter(r.specifier)).version)
    return out


def _generated():
    lines = [ln.strip() for ln in gen_lambda_requirements().splitlines() if ln.strip() and not ln.startswith("#")]
    return {_norm(r.name): r for r in map(Requirement, lines)}


def test_lambda_pins_are_exact_and_not_older_than_the_lock():
    lock = _lock()
    for name, req in _generated().items():
        spec = next(iter(req.specifier))
        assert spec.operator == "==", f"{name} must be pinned exactly"
        if name in lock:
            assert Version(spec.version) >= lock[name], f"{name}=={spec.version} is older than requirements.lock ({lock[name]})"


def test_lambda_requirements_use_sqlalchemy_asyncio_extra():
    assert "asyncio" in _generated()["sqlalchemy"].extras


def test_every_install_path_uses_the_lock():
    """Dockerfiles, deploy scripts and workflows must install requirements.lock, never the floors in requirements.txt."""
    files = [*ROOT.glob("Dockerfile*"), *ROOT.glob("deploy/**/*.sh"), *ROOT.glob(".github/workflows/*.yml")]
    bad = []
    for f in files:
        for ln in f.read_text().splitlines():
            if re.search(r"pip3?\s+install\b.*-r\s+\S*requirements\.txt", ln) and not ln.lstrip().startswith("#"):
                bad.append(f"{f.relative_to(ROOT)}: {ln.strip()}")
    assert not bad, bad
