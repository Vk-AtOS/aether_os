"""Bare entity labels become generator entities (acceptance run 13, 22 Nov 2026): `users` -> class User, table users."""
from __future__ import annotations

import pytest

from aether_os.phases.p07a_unit_testing.task_agent import _entity_from_label, _generate_crud_tests, _reject_crud_fix


@pytest.mark.parametrize("label, name, table", [
    ("users", "User", "users"), ("User", "User", "users"), ("tasks", "Task", "tasks"), ("Task", "Task", "tasks"),
    ("categories", "Category", "categories"), ("Category", "Category", "categories"), ("statuses", "Status", "statuses"),
    ("Status", "Status", "statuses"), ("task_items", "TaskItem", "task_items"), ("TaskItem", "TaskItem", "task_items"),
    ("addresses", "Address", "addresses"), ("boxes", "Box", "boxes"), ("days", "Day", "days"), ("---", "Item", "items"),
])
def test_label_to_entity(label, name, table):
    assert _entity_from_label(label) == {"name": name, "table": table}


def test_generated_tests_use_the_real_table(tmp_path):
    code = _generate_crud_tests(None, "x", [_entity_from_label("users"), _entity_from_label("projects")])
    assert "/api/projects" in code and "/api/projectss" not in code


GOOD = "all_routers = []\n" + "x = 1\n" * 100


def test_reject_truncated_or_shrunken_rewrites():
    assert "syntax error" in _reject_crud_fix("obj = models.User(**data.model_dump(exclude_u", GOOD)
    assert _reject_crud_fix("y = 2\n" * 200, GOOD) == "drops all_routers"
    assert "lost most" in _reject_crud_fix("all_routers = []\n", GOOD)
    assert _reject_crud_fix(GOOD, GOOD) == ""
