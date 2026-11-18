"""KAN-63: quality metrics read generated files through safe_fs; DB errors hide bound values."""
import pytest
from sqlalchemy import text

from aether_os.core import db
from aether_os.core.quality import metrics


def test_seed_symlink_is_not_followed(tmp_path):
    outside = tmp_path / "outside.py"
    outside.write_text("\n".join(f"Thing{i}(x=1)" for i in range(30)))
    proj = tmp_path / "proj"
    src = proj / "src"
    src.mkdir(parents=True)
    (src / "seed.py").symlink_to(outside)
    assert metrics._check_seed_quality(src) == 0.0


def test_route_scan_ignores_symlinked_files(tmp_path):
    outside = tmp_path / "o.py"
    outside.write_text("from fastapi import APIRouter\nr = APIRouter()\n@r.get('/a')\ndef a(): pass\n")
    src = tmp_path / "proj" / "src"
    src.mkdir(parents=True)
    (src / "r.py").symlink_to(outside)
    assert metrics._collect_all_routes(src) == []


def test_real_files_still_scored(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "seed.py").write_text("\n".join(f"Thing{i}(x=1)" for i in range(12)))
    assert metrics._check_seed_quality(src) == 1.0


@pytest.mark.asyncio
async def test_bound_values_not_in_error_text(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/h.db")
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)
    engine = db.get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE t (a INTEGER PRIMARY KEY)"))
        with pytest.raises(Exception) as ei:
            await conn.execute(text("INSERT INTO nope (a) VALUES (:v)"), {"v": "s3cret-value"})
    assert "s3cret-value" not in str(ei.value)
    await engine.dispose()


def _outside_backend(tmp_path):
    out = tmp_path / "outside" / "src"
    out.mkdir(parents=True)
    (out / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n@app.get('/x')\ndef x(): pass\n")
    (out / "seed.py").write_text("\n".join(f"Thing{i}(x=1)" for i in range(30)))
    return out


def test_symlinked_src_dir_is_not_scored(tmp_path):
    out = _outside_backend(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "src").symlink_to(out)
    assert metrics._find_real_src_dir(proj) is None
    assert metrics.score_project(proj).api_endpoint_count == 0


def test_symlinked_parent_of_src_dir_is_not_scored(tmp_path):
    out = _outside_backend(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "p04a_backend_codegen").symlink_to(out.parent)
    assert metrics._find_real_src_dir(proj) is None


def test_src_dir_outside_root_is_refused(tmp_path):
    out = _outside_backend(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    with pytest.raises(Exception):
        metrics._collect_all_routes(out, proj)


def test_symlinked_file_inside_real_src_dir_not_read(tmp_path):
    out = _outside_backend(tmp_path)
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "main.py").write_text("x = 1\n")
    (proj / "src" / "seed.py").symlink_to(out / "seed.py")
    assert metrics._check_seed_quality(proj / "src", proj) == 0.0


def test_other_readers_do_not_follow_links(tmp_path):
    from aether_os.core.compliance.code_scanner import scan_file
    from aether_os.core.compliance.manifest_writer import _compute_drift_fingerprint
    from aether_os.core.quality.dimension_critic import critique_directory
    out = tmp_path / "out"
    out.mkdir()
    (out / "evil.py").write_text("@router.get('/leak')\ndef leak(): pass\n")
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "main.py").write_text("x = 1\n")
    (proj / "src" / "r.py").symlink_to(out / "evil.py")
    (proj / "linked").symlink_to(out)
    assert not scan_file(proj / "src" / "main.py", root=proj).routes
    import hashlib
    assert _compute_drift_fingerprint(proj) == hashlib.sha256(b"").hexdigest()
    assert len(critique_directory(str(proj))) == 1   # main.py only; r.py and linked/ are links
