"""KAN-121: the password-reset email link must land inside the SPA (served under /dashboard)."""
from aether_os.gateway.routers.auth_password_router import reset_link_for


def test_reset_link_carries_dashboard_base():
    assert reset_link_for("https://app.test/", "tok") == "https://app.test/dashboard/reset-password?token=tok"
    assert reset_link_for("https://app.test/dashboard", "a b") == "https://app.test/dashboard/reset-password?token=a%20b"
