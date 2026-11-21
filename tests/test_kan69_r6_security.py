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
