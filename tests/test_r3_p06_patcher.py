"""KAN-100 p06: AST patching works without the astor package, keeps the module importable, and does not invent a secret."""
import runpy

from aether_os.phases.p06_review_security.patcher import ASTSecurityPatcher


def test_secret_key_patch_needs_no_astor_adds_import_os_and_fails_closed(tmp_path, monkeypatch):
    f = tmp_path / "cfg.py"
    f.write_text('"""doc"""\nfrom __future__ import annotations\n\nSECRET_KEY = "hunter2"\n')
    patcher = ASTSecurityPatcher()
    patcher.patch_file(str(f))
    assert "secret_key_hardening" in patcher.patches_applied
    text = f.read_text()
    assert "hunter2" not in text and "import os" in text and text.index("__future__") < text.index("import os")
    monkeypatch.setenv("SECRET_KEY", "from-env")
    assert runpy.run_path(str(f))["SECRET_KEY"] == "from-env"
    monkeypatch.delenv("SECRET_KEY")
    try:
        runpy.run_path(str(f))
    except KeyError:
        pass
    else:
        raise AssertionError("a missing SECRET_KEY must stop the app, not fall back to a random per-process key")
