"""
Tests for SLM Prompt Templates.
"""

from __future__ import annotations
from src.slm.prompt_templates import PromptTemplates

def test_get_template_connection_timeout():
    template = PromptTemplates.get_template("ConnectionTimeout")
    assert "retry" in template["strategy"]
    assert "exponential backoff" in template["strategy"]

def test_get_template_unknown_falls_back():
    template = PromptTemplates.get_template("SomeRandomError")
    assert template["system"] == PromptTemplates.BASE_SYSTEM
    assert "Analyze the error" in template["strategy"]

def test_build_prompt_returns_tuple():
    system, user = PromptTemplates.build_prompt(
        "AttributeError", "log content", "file content", "test.py"
    )
    assert isinstance(system, str)
    assert isinstance(user, str)
    assert len(system) > 0
    assert len(user) > 0

def test_build_prompt_includes_log_content():
    log_text = "ERROR: something went wrong"
    _, user = PromptTemplates.build_prompt(
        "ImportError", log_text, "content", "app.py"
    )
    assert log_text in user
    assert "app.py" in user
