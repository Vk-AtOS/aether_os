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
    # only the reviewed chromadb server-mode ids may be ignored; a new ignore must be added here on purpose
    assert s.count("--ignore-vuln") == 4 and "PersistentClient" in s


def test_secret_scan_uses_the_reviewed_config_and_never_allowlists_real_secret_files():
    assert "--config .gitleaks.toml" in (ROOT / "scripts" / "ci" / "secret_scan.sh").read_text()
    cfg = (ROOT / ".gitleaks.toml").read_text()
    for real in ("plans2", "auth_res", "token\\.txt", "AUDIT_REPORT", "HARDENING_REPORT", "dcsp", "READINESS"):
        assert real not in cfg, real
