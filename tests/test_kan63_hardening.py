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
