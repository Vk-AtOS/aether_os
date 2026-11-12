"""Outbound HTTP to user-supplied URLs: resolve once, check every address, connect
to the checked address with the original Host header and TLS SNI. Webhook
delivery, POST /webhooks/{id}/test and webhook URL edits all use it.

DNS (socket.getaddrinfo) and the HTTP transport are replaced: no network is used.
The SSRF checks, pinning and gateway routes run for real.
"""
from __future__ import annotations

import socket
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from aether_os.core.security import safe_http
from aether_os.core.security.safe_http import UnsafeURL, check_url_shape, resolve_public, safe_request
from aether_os.core.webhooks.delivery import _assert_safe_url, _delivery


def _dns(*addresses):
    calls = []

    def fake(host, port, *a, **k):
        calls.append(host)
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
                for ip in addresses]
    fake.calls = calls
    return fake


class Capture:
    """Stands in for httpx.AsyncClient.request: records what would be sent."""

    def __init__(self, status=200):
        self.status, self.sent = status, []

    async def __call__(self, client, method, url, **kwargs):
        self.sent.append({"method": method, "url": str(url), **kwargs,
                          "trust_env": client._trust_env, "follow_redirects": client.follow_redirects})
        return httpx.Response(self.status, request=httpx.Request(method, url))

    @property
    def fn(self):
        """A plain function, so it binds as a method when set on httpx.AsyncClient."""
        async def request(client, method, url, **kwargs):
            return await self(client, method, url, **kwargs)
        return request


@pytest.mark.parametrize("addresses", [
    ("93.184.216.34", "10.0.0.5"),        # one public, one private: refused (only the first was checked)
    ("127.0.0.1",), ("169.254.169.254",), ("::1",), ("::ffff:10.0.0.1",), ("100.64.0.1",), ("0.0.0.0",),
])
def test_every_resolved_address_must_be_public(monkeypatch, addresses):
    monkeypatch.setattr(socket, "getaddrinfo", _dns(*addresses))
    with pytest.raises(UnsafeURL):
        resolve_public("https://hooks.example.com/in")
    with pytest.raises(ValueError):
        _assert_safe_url("https://hooks.example.com/in")   # kept for Prime's executor


@pytest.mark.parametrize("url", ["ftp://example.com/x", "https:///nohost", "http://localhost/x",
                                 "http://app.localhost/x", "http://10.1.2.3/x", "http://[::1]/x",
                                 "http://metadata.google.internal/x", "http://example.com:99999/x"])
def test_url_shape_refuses_without_dns(url):
    with pytest.raises(UnsafeURL):
        check_url_shape(url)


@pytest.mark.asyncio
async def test_request_is_pinned_to_the_checked_address_with_host_and_sni(monkeypatch):
    dns = _dns("93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946")
    monkeypatch.setattr(socket, "getaddrinfo", dns)
    cap = Capture()
    monkeypatch.setattr(httpx.AsyncClient, "request", cap.fn)

    resp = await safe_request("POST", "https://hooks.example.com:8443/in?x=1", content=b"{}",
                              headers={"X-A": "1"})

    assert resp.status_code == 200 and dns.calls == ["hooks.example.com"]   # resolved once
    sent = cap.sent[0]
    assert sent["url"] == "https://93.184.216.34:8443/in?x=1"
    assert sent["headers"]["Host"] == "hooks.example.com:8443" and sent["headers"]["X-A"] == "1"
    assert sent["extensions"] == {"sni_hostname": "hooks.example.com"}
    assert sent["trust_env"] is False and sent["follow_redirects"] is False


@pytest.mark.asyncio
async def test_ipv6_address_is_bracketed(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _dns("2606:2800:220:1:248:1893:25c8:1946"))
    cap = Capture()
    monkeypatch.setattr(httpx.AsyncClient, "request", cap.fn)
    await safe_request("GET", "http://hooks.example.com/in")
    assert cap.sent[0]["url"] == "http://[2606:2800:220:1:248:1893:25c8:1946]/in"
    assert cap.sent[0]["extensions"] == {}


@pytest.mark.asyncio
async def test_webhook_delivery_uses_the_pinned_sender(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _dns("10.0.0.7"))
    cap = Capture()
    monkeypatch.setattr(httpx.AsyncClient, "request", cap.fn)
    assert await _delivery.send("https://hooks.example.com/in", "s3cret", "pipeline.complete", {}) is False
    assert cap.sent == []   # refused before any connection

    monkeypatch.setattr(socket, "getaddrinfo", _dns("93.184.216.34"))
    assert await _delivery.send("https://hooks.example.com/in", "s3cret", "pipeline.complete", {}) is True
    assert cap.sent[0]["url"] == "https://93.184.216.34/in"
    assert cap.sent[0]["headers"]["X-AetherOS-Signature-256"].startswith("sha256=")


def test_webhook_test_route_is_ssrf_checked_and_signed(gw, monkeypatch):
    owner = gw.register("whtest")
    created = gw.client.post("/webhooks", headers=owner.auth, json={"url": "https://hooks.example.com/in"})
    assert created.status_code == 200, created.text
    wh_id = created.json()["id"]
    cap = Capture()
    monkeypatch.setattr(httpx.AsyncClient, "request", cap.fn)

    monkeypatch.setattr(socket, "getaddrinfo", _dns("192.168.1.10"))
    refused = gw.client.post(f"/webhooks/{wh_id}/test", headers=owner.auth)
    assert refused.status_code == 200 and refused.json()["ok"] is False
    assert refused.json()["message"].startswith("Refused") and cap.sent == []

    monkeypatch.setattr(socket, "getaddrinfo", _dns("93.184.216.34"))
    ok = gw.client.post(f"/webhooks/{wh_id}/test", headers=owner.auth)
    assert ok.json()["ok"] is True
    assert cap.sent[0]["url"] == "https://93.184.216.34/in"
    assert cap.sent[0]["headers"]["X-AetherOS-Signature-256"].startswith("sha256=")


def test_webhook_url_edit_is_validated_like_creation(gw):
    owner = gw.register("whedit")
    wh_id = gw.client.post("/webhooks", headers=owner.auth, json={"url": "https://hooks.example.com/in"}).json()["id"]
    for bad in ("http://127.0.0.1/x", "http://localhost/x", "file:///etc/passwd"):
        resp = gw.client.put(f"/webhooks/{wh_id}", headers=owner.auth, json={"url": bad})
        assert resp.status_code == 422, bad
    assert gw.client.post("/webhooks", headers=owner.auth, json={"url": "http://10.0.0.1/x"}).status_code == 422


def test_self_hosted_gitlab_fetch_is_pinned(gw, monkeypatch):
    owner = gw.register("gitlabssrf")
    monkeypatch.setattr(socket, "getaddrinfo", _dns("10.0.0.9"))
    cap = Capture()
    monkeypatch.setattr(httpx.AsyncClient, "request", cap.fn)
    resp = gw.client.post("/factory/fetch-repo", headers=owner.auth, json={
        "type": "gitlab", "url": "https://git.internal.example/grp/repo", "gitlab_url": "https://git.internal.example"})
    assert resp.status_code == 422 and cap.sent == []


