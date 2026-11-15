"""
Tests for core/quality/metrics.py — score_project() and helpers.
All tests use temporary directories with synthetic FastAPI code; no LLM calls.
"""
from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_project(
    tmp_path: Path,
    main_py: str = "",
    has_dockerfile: bool = False,
    has_env_example: bool = False,
    has_readme: bool = False,
    has_frontend: bool = False,
    test_files: int = 0,
    compliance_file: bool = False,
) -> Path:
    """Create a minimal project directory for scoring."""
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "main.py").write_text(main_py)

    if has_dockerfile:
        (tmp_path / "Dockerfile").write_text("FROM python:3.11\n")
    if has_env_example:
        (tmp_path / ".env.example").write_text("SECRET_KEY=\nDATABASE_URL=\n")
    if has_readme:
        (tmp_path / "README.md").write_text("# Project\n")
    if has_frontend:
        fe = tmp_path / "frontend"
        fe.mkdir()
        (fe / "package.json").write_text('{"name": "app"}')
    for i in range(test_files):
        (src / f"test_route_{i}.py").write_text("def test_placeholder(): pass\n")
    if compliance_file:
        (tmp_path / "compliance_scan.json").write_text('{"status": "pass"}')

    return tmp_path


# Simple main.py with two routes: one public, one protected
_MAIN_WITH_AUTH = """\
from fastapi import FastAPI, Depends
from pydantic import BaseModel

app = FastAPI()

class ItemCreate(BaseModel):
    name: str
    price: float

def get_current_user():
    pass

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/items")
def list_items(user=Depends(get_current_user)):
    return []

@app.post("/items")
def create_item(data: ItemCreate, user=Depends(get_current_user)):
    return data
"""

_MAIN_NO_AUTH = """\
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class ItemCreate(BaseModel):
    name: str

@app.get("/items")
def list_items():
    return []

@app.post("/items")
def create_item(data: ItemCreate):
    return data
"""

_MAIN_ROUTER_STYLE = """\
from fastapi import APIRouter, Depends
from pydantic import BaseModel

router = APIRouter()

class Payload(BaseModel):
    value: int

def verify_token():
    pass

@router.get("/data")
def get_data(user=Depends(verify_token)):
    return []

@router.post("/data")
def create_data(payload: Payload, user=Depends(verify_token)):
    return payload
"""


# ─────────────────────────────────────────────────────────────────────────────
# Tests: _extract_routes
# ─────────────────────────────────────────────────────────────────────────────

def test_extract_routes_counts_app_routes():
    from aether_os.core.quality.metrics import _extract_routes
    routes = _extract_routes(_MAIN_WITH_AUTH)
    # health + /items GET + /items POST
    assert len(routes) == 3


def test_extract_routes_detects_auth():
    from aether_os.core.quality.metrics import _extract_routes
    routes = _extract_routes(_MAIN_WITH_AUTH)
    route_map = {r.path: r for r in routes}
    # /items (both GET and POST) should have auth detected via Depends(get_current_user)
    items_routes = [r for r in routes if r.path == "/items"]
    assert all(r.has_auth for r in items_routes)


def test_extract_routes_detects_no_auth():
    from aether_os.core.quality.metrics import _extract_routes
    routes = _extract_routes(_MAIN_NO_AUTH)
    for r in routes:
        assert r.has_auth is False


def test_extract_routes_router_style():
    """Router-decorated routes (@router.get) must be parsed, not just @app."""
    from aether_os.core.quality.metrics import _extract_routes
    routes = _extract_routes(_MAIN_ROUTER_STYLE)
    assert len(routes) == 2
    for r in routes:
        assert r.has_auth is True


def test_extract_routes_input_validation_on_post():
    from aether_os.core.quality.metrics import _extract_routes
    routes = _extract_routes(_MAIN_WITH_AUTH)
    post = next(r for r in routes if r.method == "POST")
    assert post.has_input_validation is True


def test_extract_routes_no_validation_on_get():
    from aether_os.core.quality.metrics import _extract_routes
    routes = _extract_routes(_MAIN_WITH_AUTH)
    get_routes = [r for r in routes if r.method == "GET"]
    for r in get_routes:
        assert r.has_input_validation is False


# ─────────────────────────────────────────────────────────────────────────────
# Tests: score_project
# ─────────────────────────────────────────────────────────────────────────────

def test_score_project_auth_coverage(tmp_path):
    from aether_os.core.quality.metrics import score_project
    proj = _make_project(tmp_path, main_py=_MAIN_WITH_AUTH)
    score = score_project(proj)
    # /health is public; /items GET and POST are both protected → 100% auth coverage
    assert score.auth_coverage == 100


def test_score_project_no_auth_gives_low_coverage(tmp_path):
    from aether_os.core.quality.metrics import score_project
    proj = _make_project(tmp_path, main_py=_MAIN_NO_AUTH)
    score = score_project(proj)
    assert score.auth_coverage == 0


def test_score_project_validation_score(tmp_path):
    from aether_os.core.quality.metrics import score_project
    proj = _make_project(tmp_path, main_py=_MAIN_WITH_AUTH)
    score = score_project(proj)
    # One POST with a Pydantic model → 100% validation
    assert score.input_validation == 100


def test_score_project_test_score_no_tests(tmp_path):
    from aether_os.core.quality.metrics import score_project
    proj = _make_project(tmp_path, main_py=_MAIN_WITH_AUTH)
    score = score_project(proj)
    assert score.test_coverage == 0


def test_score_project_test_score_one_test_file(tmp_path):
    from aether_os.core.quality.metrics import score_project
    proj = _make_project(tmp_path, main_py=_MAIN_WITH_AUTH, test_files=1)
    score = score_project(proj)
    assert score.test_coverage == 60


def test_score_project_test_score_multiple_test_files(tmp_path):
    from aether_os.core.quality.metrics import score_project
    proj = _make_project(tmp_path, main_py=_MAIN_WITH_AUTH, test_files=3)
    score = score_project(proj)
    assert score.test_coverage == 60


def test_score_project_has_docker(tmp_path):
    from aether_os.core.quality.metrics import score_project
    proj = _make_project(tmp_path, main_py=_MAIN_WITH_AUTH, has_dockerfile=True)
    score = score_project(proj)
    assert score.has_docker is True


def test_score_project_no_docker(tmp_path):
    from aether_os.core.quality.metrics import score_project
    proj = _make_project(tmp_path, main_py=_MAIN_WITH_AUTH)
    score = score_project(proj)
    assert score.has_docker is False


def test_score_project_has_env_example(tmp_path):
    from aether_os.core.quality.metrics import score_project
    proj = _make_project(tmp_path, main_py=_MAIN_WITH_AUTH, has_env_example=True)
    score = score_project(proj)
    assert score.has_env_example is True


def test_score_project_has_readme(tmp_path):
    from aether_os.core.quality.metrics import score_project
    proj = _make_project(tmp_path, main_py=_MAIN_WITH_AUTH, has_readme=True)
    score = score_project(proj)
    assert score.has_readme is True


def test_score_project_has_frontend(tmp_path):
    from aether_os.core.quality.metrics import score_project
    proj = _make_project(tmp_path, main_py=_MAIN_WITH_AUTH, has_frontend=True)
    score = score_project(proj)
    assert score.has_frontend is True


def test_score_project_has_compliance(tmp_path):
    from aether_os.core.quality.metrics import score_project
    proj = _make_project(tmp_path, main_py=_MAIN_WITH_AUTH, compliance_file=True)
    score = score_project(proj)
    assert score.has_compliance_report is True


def test_score_project_total_is_int(tmp_path):
    from aether_os.core.quality.metrics import score_project
    proj = _make_project(tmp_path, main_py=_MAIN_WITH_AUTH)
    score = score_project(proj)
    assert isinstance(score.total, int)
    assert 0 <= score.total <= 100


def test_score_project_full_features_gives_high_total(tmp_path):
    """A project with auth + docker + readme + env.example should score > 70."""
    from aether_os.core.quality.metrics import score_project
    proj = _make_project(
        tmp_path,
        main_py=_MAIN_WITH_AUTH,
        has_dockerfile=True,
        has_env_example=True,
        has_readme=True,
        has_frontend=True,
        compliance_file=True,
        test_files=2,
    )
    score = score_project(proj)
    assert score.total > 70


def test_score_project_empty_directory(tmp_path):
    """Empty directory should not crash — returns 0-score."""
    from aether_os.core.quality.metrics import score_project
    score = score_project(tmp_path)
    assert isinstance(score.total, int)
    assert score.total >= 0


def test_score_project_api_count(tmp_path):
    from aether_os.core.quality.metrics import score_project
    proj = _make_project(tmp_path, main_py=_MAIN_WITH_AUTH)
    score = score_project(proj)
    assert score.api_endpoint_count == 3


def test_score_project_details_dict(tmp_path):
    from aether_os.core.quality.metrics import score_project
    proj = _make_project(tmp_path, main_py=_MAIN_WITH_AUTH)
    score = score_project(proj)
    assert "routes" in score.details
    assert score.details["routes"] == 3


def test_score_project_router_style_routes(tmp_path):
    """Router-decorated routes should be parsed just like @app routes."""
    from aether_os.core.quality.metrics import score_project
    proj = _make_project(tmp_path, main_py=_MAIN_ROUTER_STYLE)
    score = score_project(proj)
    # Both routes have auth
    assert score.auth_coverage == 100
    assert score.api_endpoint_count == 2
