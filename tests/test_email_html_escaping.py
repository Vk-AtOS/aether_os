"""KAN-110: user-supplied text must be HTML-escaped in every e-mail body the platform sends."""
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from aether_os.core.notifications.email import EmailNotifier
from aether_os.gateway.routers import questionnaire_helpers
from aether_os.gateway.services import admin_service

EVIL = "<img src=x onerror=alert(1)>"


def test_questionnaire_email_escapes_name_agency_and_stage(monkeypatch):
    monkeypatch.setenv("SENDGRID_API_KEY", "k")
    sent = {}

    class _Client:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            sent.update(json)
            return MagicMock(status_code=202)

    with patch.object(questionnaire_helpers.httpx, "AsyncClient", _Client):
        ok = asyncio.run(questionnaire_helpers._send_email_via_sendgrid(
            "a@b.c", EVIL, EVIL, "https://x/q/tok'><script>", EVIL, datetime(2026, 1, 1)))
    assert ok
    body = sent["content"][0]["value"]
    assert "<img" not in body and "<script>" not in body and "'><" not in body
    assert body.count("&lt;img src=x") == 3


def test_run_and_decision_emails_escape_project_name_and_phase():
    n = EmailNotifier()
    n.send = AsyncMock(return_value=True)
    asyncio.run(n.notify_run_complete("a@b.c", EVIL, "r1", 0.1))
    asyncio.run(n.notify_run_failed("a@b.c", EVIL, "r1"))
    asyncio.run(n.notify_decision_required("a@b.c", EVIL, "r1", EVIL))
    assert n.send.call_count == 3
    for call in n.send.call_args_list:
        assert "<img" not in call.args[2] and "&lt;img" in call.args[2]


def test_invite_email_escapes_inviter_name():
    notifier = MagicMock(send=AsyncMock(return_value=True))
    with patch("aether_os.core.notifications.email.get_email_notifier", return_value=notifier):
        assert asyncio.run(admin_service._send_invite_email("a@b.c", "p<w&d", EVIL))
    html = notifier.send.call_args.args[2]
    assert "<img" not in html and "&lt;img" in html and "p&lt;w&amp;d" in html
    assert "p<w&d" in notifier.send.call_args.args[3]   # the plain-text part keeps the real password
