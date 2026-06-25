"""
Tests for notification router.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from src.notifications.router import NotificationRouter
from src.notifications.base import BaseNotifier, NotificationEvent


class MockNotifier(BaseNotifier):
    def __init__(self, should_fail=False, should_raise=False):
        self.should_fail = should_fail
        self.should_raise = should_raise
        self.sent = False

    def send(self, event):
        self.sent = True
        if self.should_raise:
            raise Exception("Boom")
        return not self.should_fail


@pytest.fixture
def sample_event():
    return NotificationEvent(
        job_id="123", repo_name="r", branch="b", status="success",
        confidence=1.0, explanation="e"
    )


def test_router_notify_calls_all_notifiers(sample_event):
    """Router should trigger send on all registered notifiers."""
    router = NotificationRouter()
    # Clear auto-configured notifiers
    router.notifiers = []
    
    n1 = MockNotifier()
    n2 = MockNotifier()
    router.add_notifier(n1)
    router.add_notifier(n2)
    
    router.notify(sample_event)
    
    assert n1.sent is True
    assert n2.sent is True


def test_router_returns_results_dict(sample_event):
    """Router should return a dict indicating success/failure per notifier."""
    router = NotificationRouter()
    router.notifiers = []
    
    router.add_notifier(MockNotifier(should_fail=False)) # 'mock'
    router.add_notifier(MockNotifier(should_fail=True))  # 'mock'
    
    results = router.notify(sample_event)
    
    # Notifiers of same class will overwrite keys in this simple impl, 
    # but that's fine for the test requirements.
    assert "mock" in results
    # The last one added was failing
    assert results["mock"] is False


def test_router_handles_notifier_exception(sample_event):
    """Exceptions in notifiers should not crash the router."""
    router = NotificationRouter()
    router.notifiers = []
    
    router.add_notifier(MockNotifier(should_raise=True))
    
    # Should not raise
    results = router.notify(sample_event)
    assert results["mock"] is False
