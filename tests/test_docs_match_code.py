"""KAN-181: the docs must not name routes, paths, env vars or scripts the code does not have."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_docs", ROOT / "scripts/ci/check_docs.py")
check_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_docs)


def test_docs_match_code():
    out = []
    check_docs.check_routes(out)
    check_docs.check_paths_env_cmds(out)
    assert not out, "\n".join(out)


def test_checker_detects_invented_names(tmp_path, monkeypatch):
    doc = tmp_path / "README.md"
    doc.write_text("See `core/nope_missing.py` and `NOPE_ENV_VAR_X`.\nRun `bash scripts/ci/missing.sh`.\n"
                   "There is no `core/never.py`.\n")
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)
    out = []
    check_docs.check_paths_env_cmds(out, docs=["README.md"], src="")
    assert len(out) == 3, out
