"""p07a must accept entities given as bare names (production acceptance run 9, 22 Nov 2026)."""
from aether_os.phases.p07a_unit_testing.task_agent import _generate_crud_tests, _normalise_entities


def test_string_entities_become_dicts():
    assert _normalise_entities(["Task", {"name": "Project"}, "", 3]) == [{"name": "Task", "table": "tasks"}, {"name": "Project"}]
    assert _normalise_entities("Task") == [] and _normalise_entities(None) == []


def test_crud_tests_generate_from_bare_entity_names():
    code = _generate_crud_tests(None, "App", _normalise_entities(["User", "Task"]))
    assert "/api/tasks" in code
    compile(code, "test_main.py", "exec")
