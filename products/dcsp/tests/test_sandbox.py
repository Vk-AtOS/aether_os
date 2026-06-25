from __future__ import annotations
import pytest
from src.sandbox.docker_sandbox import (
    is_sandbox_available,
    run_in_sandbox,
    validate_patch_in_sandbox,
    _apply_simple_patch,
    SandboxResult,
    DOCKER_AVAILABLE
)

def test_sandbox_available_returns_bool():
    result = is_sandbox_available()
    assert isinstance(result, bool)

def test_sandbox_result_dataclass():
    r = SandboxResult(
        success=True,
        exit_code=0,
        stdout="hello",
        stderr=""
    )
    assert r.success is True
    assert r.exit_code == 0
    assert r.timed_out is False

def test_run_in_sandbox_no_docker():
    """When Docker unavailable, returns graceful result."""
    result = run_in_sandbox("print('hello')", "python")
    assert isinstance(result, SandboxResult)
    assert isinstance(result.success, bool)
    assert isinstance(result.exit_code, int)
    # If Docker unavailable, docker_available=False
    if not DOCKER_AVAILABLE:
        assert result.docker_available is False
        assert result.success is False

def test_validate_patch_no_docker():
    """validate_patch gracefully handles missing Docker."""
    result = validate_patch_in_sandbox(
        "x = 1\n",
        "+x = 2\n-x = 1\n",
        "python"
    )
    assert isinstance(result, SandboxResult)
    assert isinstance(result.success, bool)

def test_apply_simple_patch_addition():
    original = "x = 1\n"
    patch = "+x = 2\n-x = 1\n"
    result = _apply_simple_patch(original, patch)
    assert "x = 2" in result

def test_apply_simple_patch_empty():
    """Empty patch returns original."""
    original = "x = 1\n"
    result = _apply_simple_patch(original, "")
    assert result == original

def test_apply_simple_patch_context_lines():
    """Context lines (space prefix) kept."""
    patch = " import os\n+x = 1\n"
    result = _apply_simple_patch("", patch)
    assert "import os" in result
    assert "x = 1" in result

def test_apply_simple_patch_skips_headers():
    """Headers (+++, ---, @@) are skipped."""
    patch = (
        "--- a/file.py\n"
        "+++ b/file.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-old = 1\n"
        "+new = 1\n"
    )
    result = _apply_simple_patch("old = 1\n", patch)
    assert "new = 1" in result
    assert "---" not in result
    assert "+++" not in result

def test_sandbox_status_api():
    """Sandbox status endpoint works."""
    from fastapi.testclient import TestClient
    from src.api.main import app
    from src.api.auth import ACTIVE_SESSIONS
    token = "sandbox_status_token"
    ACTIVE_SESSIONS[token] = "admin"
    client = TestClient(app)
    response = client.get(
        "/api/sandbox/status",
        cookies={"session_token": token}
    )
    assert response.status_code == 200
    data = response.json()
    assert "available" in data
    assert "image" in data
    assert isinstance(data["available"], bool)
