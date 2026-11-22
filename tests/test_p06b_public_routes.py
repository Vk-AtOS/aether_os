"""KAN-109: login/health routes are public by design and must not fail the formal-verification gate."""
import importlib.util

import pytest

from aether_os.phases.p06b_formal_verification.z3_checkers import _check_inv001_auth
from aether_os.phases.p06b_formal_verification.z3_encoder import RouteInfo


@pytest.mark.parametrize("path", ["/auth/login", "/api/auth/register", "/health", "/refresh/", "/openapi.json"])
def test_public_routes_are_not_violations(path):
    assert _check_inv001_auth(RouteInfo(name="r", path=path, method="POST")).status == "N/A"


@pytest.mark.skipif(importlib.util.find_spec("z3") is None, reason="z3 not installed here")
def test_unprotected_data_route_is_still_a_violation():
    assert _check_inv001_auth(RouteInfo(name="r", path="/api/invoices", method="GET")).status == "VIOLATED"


@pytest.mark.skipif(importlib.util.find_spec("z3") is None, reason="z3 not installed here")
def test_protected_route_verified():
    assert _check_inv001_auth(RouteInfo(name="r", path="/api/invoices", method="GET", has_auth_depends=True)).status == "VERIFIED"


@pytest.mark.parametrize("path,method", [("/", "GET"), ("", "GET"), ("/logout", "POST"), ("/api/auth/logout", "POST")])
def test_root_banner_and_logout_are_public(path, method):
    # Production acceptance run, 22 Nov 2026: GET / and POST /logout failed INV-001 and blocked s05.
    assert _check_inv001_auth(RouteInfo(name="r", path=path, method=method)).status == "N/A"


@pytest.mark.skipif(importlib.util.find_spec("z3") is None, reason="z3 not installed here")
@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_writes_on_the_root_still_need_auth(method):
    assert _check_inv001_auth(RouteInfo(name="r", path="/", method=method)).status == "VIOLATED"
