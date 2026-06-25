"""
Billing module tests.

Tests the Stripe integration helpers.
"""

from src.billing import get_subscription_status, PLAN_LIMITS


def test_plan_limits_defined():
    """All expected plans have defined limits."""
    assert "free" in PLAN_LIMITS
    assert "pro" in PLAN_LIMITS
    assert "enterprise" in PLAN_LIMITS


def test_free_plan_limit():
    assert PLAN_LIMITS["free"] == 5


def test_pro_plan_limit():
    assert PLAN_LIMITS["pro"] == 100


def test_enterprise_plan_unlimited():
    assert PLAN_LIMITS["enterprise"] is None


def test_get_subscription_status_unknown_tenant():
    """Unknown tenant returns free plan gracefully."""
    result = get_subscription_status("non-existent-tenant-id")
    assert result["plan"] in ("free", "unknown")
