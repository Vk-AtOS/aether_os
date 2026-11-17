"""KAN-69 F22: push-github always created a public repository."""
import inspect

from aether_os.gateway.routers import run_preview_router


def test_push_github_creates_a_private_repo_unless_asked_otherwise():
    src = inspect.getsource(run_preview_router.push_run_to_github)
    assert '"private": False' not in src and 'req.get("public") is not True' in src
