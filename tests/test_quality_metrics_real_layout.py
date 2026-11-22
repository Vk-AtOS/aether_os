"""Quality score on the layout the pipeline really produces (production acceptance run 15, 22 Nov 2026: 63% because
schemas in schemas.py, Optional[...] bodies and body-less routes were not recognised, and README/.env.example/
compliance_scan.json were looked for only at the run root)."""
from __future__ import annotations

from aether_os.core.quality import metrics as m

SCHEMAS = ("from pydantic import BaseModel\n"
           "class ProjectBase(BaseModel):\n    name: str\n"
           "class ProjectCreate(ProjectBase):\n    owner_id: int\n"
           "class RefreshRequest(BaseModel):\n    token: str\n")
CRUD = ("from typing import Optional\nfrom fastapi import APIRouter, Depends, Request\nimport schemas\n"
        "from schemas import ProjectCreate, RefreshRequest\n"
        "r = APIRouter()\n"
        "def user(): return {}\n"
        "@r.post('/projects')\nasync def create(data: ProjectCreate, current_user: dict = Depends(user)): ...\n"
        "@r.put('/projects/{pid}')\nasync def update(pid: int, data: schemas.ProjectCreate): ...\n"
        "@r.post('/refresh')\nasync def refresh(request: Request, data: Optional[RefreshRequest] = None): ...\n"
        "@r.post('/logout')\nasync def logout(current_user: dict = Depends(user)): ...\n"
        "@r.post('/follow/{uid}')\nasync def follow(uid: int, current_user: dict = Depends(user)): ...\n"
        "@r.post('/raw')\nasync def raw(body: dict): ...\n")


def _project(tmp_path):
    src = tmp_path / "p04_backend" / "backend_codegen" / "src"
    (src / "routers").mkdir(parents=True)
    (src / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    (src / "schemas.py").write_text(SCHEMAS)
    (src / "routers" / "crud.py").write_text(CRUD)
    return src


def test_models_from_other_modules_and_inheritance_count(tmp_path):
    src = _project(tmp_path)
    routes = {r.path: r.has_input_validation for r in m._collect_all_routes(src, tmp_path)}
    assert routes["/projects"] and routes["/projects/{pid}"] and routes["/refresh"]
    assert routes["/logout"] and routes["/follow/{uid}"]          # no body: nothing to validate
    assert routes["/raw"] is False                                # a raw dict body is unvalidated


def test_pydantic_classes_follow_inheritance():
    import ast
    assert m._pydantic_classes([ast.parse(SCHEMAS)]) == {"ProjectBase", "ProjectCreate", "RefreshRequest"}


def test_annotation_names_unwraps_optional_union_and_attributes():
    import ast
    ann = lambda s: ast.parse(f"x: {s}").body[0].annotation   # noqa: E731
    assert m._annotation_names(ann("Optional[A]")) == {"A"}
    assert m._annotation_names(ann("A | None")) == {"A"}
    assert m._annotation_names(ann("schemas.A")) == {"A"}
    assert m._annotation_names(ann("Dict[str, Any]")) == {"Dict"}


def test_readme_env_and_compliance_found_where_the_pipeline_writes_them(tmp_path):
    src = _project(tmp_path)
    (src.parent / "README.md").write_text("# app\n")
    (src.parent / ".env.example").write_text("DATABASE_URL=\n")
    comp = tmp_path / "p06_review_security" / "compliance"
    comp.mkdir(parents=True)
    (comp / "compliance_scan.json").write_text("{}")
    q = m.score_project(tmp_path)
    assert q.has_readme and q.has_env_example and q.has_compliance_report