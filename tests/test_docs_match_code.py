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
    check_docs.check_alembic_head(out)
    check_docs.check_repo_stats(out)
    assert not out, "\n".join(out)


def test_checker_detects_invented_names(tmp_path, monkeypatch):
    doc = tmp_path / "README.md"
    doc.write_text("See `core/nope_missing.py` and `NOPE_ENV_VAR_X`.\nRun `bash scripts/ci/missing.sh`.\n"
                   "There is no `core/never.py`.\n")
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)
    out = []
    check_docs.check_paths_env_cmds(out, docs=["README.md"], src="")
    assert len(out) == 3, out


def test_stale_numbers_in_the_sale_documents_are_detected(tmp_path, monkeypatch):
    """KAN-182: the tables are generated; a table carried over from an old branch fails the check."""
    spec = importlib.util.spec_from_file_location("repo_stats", ROOT / "scripts/ci/repo_stats.py")
    rs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rs)
    now = rs.stats()
    assert now["Tracked Python files"][0] > 1000 and now["Test files"][0] > 200
    monkeypatch.setattr(rs, "ROOT", tmp_path)
    monkeypatch.setattr(rs, "git", lambda *a: "abc1234 2026-11-19")
    (tmp_path / "A.md").write_text("intro\n" + rs.render(now) + "\ntail\n")
    assert rs.drift(["A.md"], now) == []
    stale = {k: (int(v * 0.9), how) for k, (v, how) in now.items()}          # the 88659af table was 6-15% behind
    (tmp_path / "B.md").write_text(rs.render(stale))
    problems = rs.drift(["B.md"], now)
    assert any("'Tracked Python files' says" in p for p in problems) and any("'Test files' says" in p for p in problems)
    assert not any("Git commits" in p for p in problems)                     # not re-checked (shallow clones)
    (tmp_path / "C.md").write_text("| Tests collected | 1954 |\n")
    assert "no generated repo_stats table" in rs.drift(["C.md"], now)[0]
