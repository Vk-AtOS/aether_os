"""KAN-69 round 6: regressions for findings of the whole-codebase adversarial review."""
import pytest
from fastapi import HTTPException

from aether_os.gateway.routers.account_codebase_router import import_codebase


@pytest.mark.asyncio
@pytest.mark.parametrize("repo_url,branch", [
    ("https://github.com/../user", "main"),
    ("https://github.com/owner/repo?x=1", "main"),
    ("https://github.com/owner/repo%2f..%2f..", "main"),
    ("https://github.com/owner/..", "main"),
    ("https://github.com/owner/repo", "../../../user/repos"),
    ("https://github.com/owner/repo", "main?per_page=1#"),
])
async def test_import_codebase_refuses_names_that_steer_the_platform_token(monkeypatch, repo_url, branch):
    """The request carries the platform GITHUB_TOKEN: nothing but a plain owner/repo/branch may reach the URL."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_platform")
    with pytest.raises(HTTPException) as exc:
        await import_codebase({"repo_url": repo_url, "branch": branch}, {"org_id": "o1"})
    assert exc.value.status_code == 422


def test_portal_feedback_body_is_bounded():
    """A portal token holder is an external client; feedback is appended to disk on every call."""
    from pydantic import ValidationError

    from aether_os.gateway.client_portal.routes import FeedbackBody

    assert FeedbackBody(feedback="ok", phase="p01").feedback == "ok"
    with pytest.raises(ValidationError):
        FeedbackBody(feedback="x" * 5001)
    with pytest.raises(ValidationError):
        FeedbackBody(feedback="ok", phase="p" * 129)


def test_nginx_portal_location_is_rate_limited_and_body_capped():
    """The portal location is reachable with only a portal token: it needs the same limits as /api/."""
    import re
    from pathlib import Path

    conf = re.sub(r"#[^\n]*", "", (Path(__file__).resolve().parent.parent / "deploy" / "nginx.conf").read_text())
    block = conf.split("location /portal/ {", 1)[1].split("\n    }", 1)[0]
    assert "limit_req zone=api" in block
    assert "client_max_body_size" in block


@pytest.mark.asyncio
async def test_change_password_is_throttled_per_user(monkeypatch):
    """A stolen access token must not allow unlimited guesses of the current password."""
    from types import SimpleNamespace

    from aether_os.gateway.routers import auth_password_router as r

    seen = []

    class Limiter:
        async def allow(self, key, limit, window):
            seen.append(key)
            return False

    monkeypatch.setattr(r, "_get_rl", lambda: Limiter())
    request = SimpleNamespace(client=SimpleNamespace(host="203.0.113.9"), headers={})
    with pytest.raises(HTTPException) as exc:
        await r.change_password({"current_password": "x", "new_password": "y"}, request, {"user_id": "u1"})
    assert exc.value.status_code == 429
    assert seen == ["change_pw:u1"]
