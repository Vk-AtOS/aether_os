"""KAN-121: the password-reset email link must land inside the SPA (served under /dashboard)."""
from aether_os.gateway.routers.auth_password_router import reset_link_for


def test_reset_link_carries_dashboard_base():
    assert reset_link_for("https://app.test/", "tok") == "https://app.test/dashboard/reset-password?token=tok"
    assert reset_link_for("https://app.test/dashboard", "a b") == "https://app.test/dashboard/reset-password?token=a%20b"


def test_the_link_host_comes_from_configuration_never_from_request_headers(monkeypatch):
    """A forged Host / X-Forwarded-Host header must not choose where the reset token is sent."""
    import inspect

    from aether_os.gateway.routers import auth_password_router as r
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    monkeypatch.delenv("OAUTH_REDIRECT_BASE", raising=False)
    assert r.configured_frontend_url() == ""                       # nothing configured: no link (the route sends no e-mail)
    monkeypatch.setenv("OAUTH_REDIRECT_BASE", "https://sso.test/")
    assert r.configured_frontend_url() == "https://sso.test"
    monkeypatch.setenv("FRONTEND_URL", "https://app.test/")
    assert r.configured_frontend_url() == "https://app.test"
    src = inspect.getsource(r)
    assert "x-forwarded-host" not in src and 'headers.get("host"' not in src
