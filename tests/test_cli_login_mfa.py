"""KAN-101/92: `aether login` for an MFA account must complete the challenge, not KeyError on access_token."""
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from aether_os.cli import aetheros


def _resp(body):
    r = MagicMock()
    r.json.return_value = body
    r.raise_for_status.return_value = None
    return r


def test_login_with_mfa_exchanges_code(tmp_path):
    calls = []

    def post(url, json=None, timeout=None):
        calls.append(url)
        if url.endswith("/auth/login"):
            return _resp({"mfa_required": True, "mfa_token": "challenge"})
        assert url.endswith("/auth/mfa/confirm") and json == {"mfa_token": "challenge", "code": "123456"}
        return _resp({"access_token": "real"})

    saved = {}
    with patch.object(aetheros.requests, "post", post), patch.object(aetheros, "_save_cfg", saved.update):
        res = CliRunner().invoke(
            aetheros.app, ["login", "-u", "http://x", "-e", "a@b.c", "-p", "pw"], input="123456\n")
    assert res.exit_code == 0, res.output
    assert saved["token"] == "real" and len(calls) == 2
