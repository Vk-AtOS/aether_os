"""KAN-156: Stripe return URLs from the client must be on the APP_BASE_URL origin."""
import pytest
from fastapi import HTTPException

from aether_os.gateway.routers.billing_stripe_router import _checked_return_url


def test_stripe_return_url_must_be_on_app_origin():
    base = "https://app.example.test"
    assert _checked_return_url(None, base, "/billing?x=1") == f"{base}/billing?x=1"
    assert _checked_return_url(f"{base}/dashboard/billing?a=1", base, "/b").endswith("billing?a=1")
    for evil in ("https://evil.test/x", "http://app.example.test/x", "https://app.example.test.evil.test/"):
        with pytest.raises(HTTPException):
            _checked_return_url(evil, base, "/b")
