"""Parser-differential bypasses of the connection-string check (schema import, KAN-110 follow-up): every string below
is a local file or an internal host for SQLAlchemy, whatever its prefix looks like."""
import asyncio

import pytest

from aether_os.core.schema_importer import import_schema
from aether_os.core.security.db_url import validate_db_url

BAD = [
    "sqlite+pysqlite:////etc/passwd", "sqlite+pysqlite:///../../etc/passwd", "SQLITE:///../x.db", "SqLite+PySQLite:///../../x",
    "sqlite:///file:/etc/passwd?mode=ro&uri=true", "sqlite://?uri=true&mode=ro", "sqlite:///x.db?uri=true",
    "sqlite:///file:foo", "sqlite://", "sqlite:///", "sqlite:////abs/path.db", "sqlite://localhost/x.db",
    "postgresql://u:p@/db", "postgresql:///db?host=/var/run/postgresql",     "postgresql://u:p@db.example.com/db?sslrootcert=/etc/passwd", "mysql+pymysql://u@h/db?read_default_file=/etc/passwd",
    "mysql://u@h/db?unix_socket=/tmp/s", "mssql://u:p@h/db", "oracle://u:p@h/db", "postgres://u:p@h/db",
    "file:///etc/passwd", "/etc/passwd", "not a url", "", "   ",
]


@pytest.mark.parametrize("cs", BAD)
def test_bypass_strings_are_refused(cs):
    with pytest.raises(ValueError):
        validate_db_url(cs, check_host=False)
    out = asyncio.run(import_schema(cs))
    assert out["tables"] == [] and out["error"]


def test_good_strings_pass_and_are_normalised(tmp_path):
    u = validate_db_url("SQLITE:///data/x.db", sqlite_dir=tmp_path)
    assert u.drivername == "sqlite" and u.database == str(tmp_path.resolve() / "data/x.db")
    assert validate_db_url("postgresql://u:p@db.example.com:5432/db?sslmode=require", check_host=False).host == "db.example.com"
    assert validate_db_url("mysql+pymysql://u@h/db?charset=utf8mb4", check_host=False).drivername == "mysql+pymysql"


def test_symlink_out_of_the_folder_is_refused(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "base").mkdir()
    (tmp_path / "base" / "link").symlink_to(tmp_path / "out")
    with pytest.raises(ValueError):
        validate_db_url("sqlite:///link/x.db", sqlite_dir=tmp_path / "base")
