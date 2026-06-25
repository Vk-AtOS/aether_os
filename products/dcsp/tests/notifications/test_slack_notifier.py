"""
Tests for Slack notifier.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock
from src.notifications.slack_notifier import SlackNotifier
from src.notifications.base import NotificationEvent


@pytest.fixture
def sample_event():
    return NotificationEvent(
        job_id="123",
        repo_name="acme/test",
        branch="main",
        status="success",
        confidence=0.95,
        explanation="Fixed it"
    )


def test_send_without_webhook_url_returns_false(sample_event):
    """Should return False if no webhook URL is set."""
    notifier = SlackNotifier("")
    assert notifier.send(sample_event) is False


def test_format_message_contains_repo_name(sample_event):
    """Check plain text fallback message."""
    notifier = SlackNotifier("http://fake")
    msg = notifier.format_message(sample_event)
    assert "acme/test" in msg


def test_send_calls_urllib_with_correct_url(sample_event):
    """Mock urllib and verify it's called with the webhook URL."""
    webhook_url = "https://hooks.slack.com/services/T000/B000/XXXX"
    notifier = SlackNotifier(webhook_url)
    
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        result = notifier.send(sample_event)
        
        assert result is True
        # Verify first arg of urlopen call was a Request with our url
        args, kwargs = mock_urlopen.call_args
        req = args[0]
        assert req.full_url == webhook_url
        assert req.get_method() == "POST"
        
        # Verify payload contains repo name
        payload = json.loads(req.data.decode("utf-8"))
        assert "blocks" in payload
        # Find section with repo name
        found_repo = False
        for block in payload["blocks"]:
            if block.get("type") == "section" and "fields" in block:
                for field in block["fields"]:
                    if "acme/test" in field["text"]:
                        found_repo = True
        assert found_repo is True
