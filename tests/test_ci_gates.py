"""KAN-200/203/119: the dependency audit and the secret scan are blocking and read the right inputs."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_security_gates_are_blocking_and_scripted():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "continue-on-error" not in ci
    assert "scripts/ci/audit_deps.sh" in ci and "scripts/ci/secret_scan.sh" in ci


def test_audit_reads_the_lock_file_and_every_ignore_is_justified():
    s = (ROOT / "scripts" / "ci" / "audit_deps.sh").read_text()
    assert "-r requirements.lock" in s and "set -euo pipefail" in s
    # Only reviewed ids may be ignored, and a new ignore must be added here on purpose: the four chromadb server-mode ids.
    # The five starlette advisories ignored until KAN-241 are fixed by starlette 1.x and must not come back.
    reviewed = {"PYSEC-2026-311", "PYSEC-2026-3813", "PYSEC-2026-3814", "PYSEC-2026-3815"}
    import re
    assert set(re.findall(r"--ignore-vuln (\S+)", s)) == reviewed and s.count("--ignore-vuln") == len(reviewed)
    assert "PersistentClient" in s
    for vid in reviewed:
        assert re.search(rf"^# {re.escape(vid)} .+", s, re.M), f"{vid} is ignored without a written reason"


def test_secret_scan_uses_the_reviewed_config_and_never_allowlists_real_secret_files():
    assert "--config .gitleaks.toml" in (ROOT / "scripts" / "ci" / "secret_scan.sh").read_text()
    cfg = (ROOT / ".gitleaks.toml").read_text()
    for real in ("plans2", "auth_res", "token\\.txt", "AUDIT_REPORT", "HARDENING_REPORT", "dcsp", "READINESS"):
        assert real not in cfg, real
