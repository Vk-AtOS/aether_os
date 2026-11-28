"""A run workspace laid out like a real one, built with the real generators and no model (KAN-243): the task tracker
backend (p04a) in p04_backend/backend_codegen and its frontend (p05) in frontend/. Shared by the rule-pack tests."""
from __future__ import annotations

import shutil
from pathlib import Path

from aether_os.tests.test_p04a_generated_backend import generate
from aether_os.tests.test_p05_template_typecheck import _generate

TRACKER_IR = {
    "domain": "saas", "app_name": "tracker",
    "entities": [
        {"name": "Project", "table": "projects", "fields": [
            {"name": "name", "type": "string", "nullable": False}, {"name": "description", "type": "text"},
            {"name": "status", "type": "enum", "enum_values": ["active", "archived"]}, {"name": "budget", "type": "decimal"}]},
        {"name": "Task", "table": "tasks", "fields": [
            {"name": "title", "type": "string", "nullable": False},
            {"name": "status", "type": "enum", "enum_values": ["todo", "doing", "done"]},
            {"name": "project_id", "type": "fk", "ref_entity": "Project"}, {"name": "due_date", "type": "date"},
            {"name": "estimate", "type": "integer"}]}],
    "business_rules": [],
    "permissions": [{"role": "admin", "entity": e, "actions": ["read", "create", "update", "delete"]}
                    for e in ("Project", "Task")],
}


def build_tracker_workspace(tmp_path: Path, monkeypatch) -> Path:
    """The run workspace of a task-tracker build; returns its root."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    (tmp_path / "be").mkdir(parents=True, exist_ok=True)
    _, backend = generate(tmp_path / "be", domain="saas", monkeypatch=monkeypatch, ir_override=TRACKER_IR)
    frontend = _generate(tmp_path / "fe", monkeypatch, "tracker", "ir")
    ws = tmp_path / "ws"
    shutil.copytree(backend, ws / "p04_backend" / "backend_codegen")
    shutil.copytree(frontend, ws / "frontend", ignore=shutil.ignore_patterns("node_modules"))
    return ws
