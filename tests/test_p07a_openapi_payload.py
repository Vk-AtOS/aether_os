"""Generated CRUD tests build the create body from the app's OpenAPI schema (production acceptance run 14, 22 Nov 2026:
s06 failed on `owner_id: Field required` because the body was guessed as {"name": "test"})."""
from __future__ import annotations

import asyncio
from typing import Literal, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from aether_os.phases.p07a_unit_testing.openapi_payload import PAYLOAD_HELPER
from aether_os.phases.p07a_unit_testing.task_agent import _entity_from_label, _generate_crud_tests


class ProjectCreate(BaseModel):
    name: str = Field(min_length=3)
    owner_id: int
    status: Literal["todo", "doing", "done"]
    due: Optional[str] = None
    contact_email: str
    budget: float


def _app():
    app = FastAPI()

    @app.post("/api/projects", status_code=201)
    async def create(body: ProjectCreate):
        return {"id": 1, **body.model_dump()}
    return app


class _Me:
    status_code = 200

    def json(self):
        return {"id": 42}


class _Client:
    async def get(self, path):
        assert path == "/api/auth/me"
        return _Me()


def _helpers(app):
    ns = {"app": app}
    exec(PAYLOAD_HELPER, ns)
    return ns


def test_body_has_every_required_field_and_validates():
    app = _app()
    body = asyncio.run(_helpers(app)["_payload"](_Client(), "/api/projects", {"name": "test"}))
    assert body["owner_id"] == 42 and body["status"] == "todo" and body["budget"] >= 1
    assert "@" in body["contact_email"] and "due" not in body
    ProjectCreate(**body)   # the app would accept it


def test_without_a_request_schema_the_guess_is_kept():
    app = FastAPI()
    body = asyncio.run(_helpers(app)["_payload"](_Client(), "/api/none", {"name": "test"}))
    assert body == {"name": "test"}


def test_generated_tests_use_the_helper():
    code = _generate_crud_tests(None, "x", [_entity_from_label("projects")])
    assert "async def _payload(" in code and "body = await _payload(auth_client, '/api/projects'" in code
    assert "json=body)" in code
    compile(code, "test_main.py", "exec")
