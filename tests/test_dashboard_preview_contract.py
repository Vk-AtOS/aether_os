"""The dashboard reaches generated apps only through the preview-session endpoint."""
from __future__ import annotations

import re
from pathlib import Path

from aether_os.core.run_app.preview_token import IFRAME_SANDBOX

SRC = Path(__file__).resolve().parent.parent / "dashboard" / "src"


def _sources():
    return {p: p.read_text() for p in SRC.rglob("*.js*")}


def test_no_dashboard_file_frames_or_links_a_hardcoded_preview_path():
    offenders = []
    for path, text in _sources().items():
        if path.name == "previewSession.js":
            continue
        if re.search(r'(src|href)=["\']/app-preview/', text):
            offenders.append(f"{path.name}: hard-coded /app-preview/")
        if re.search(r"<iframe[^>]*src=\{[^}]*live_url", text):
            offenders.append(f"{path.name}: iframe src from run.live_url")
    assert offenders == []


def test_iframe_sandbox_matches_the_server_and_never_allows_top_navigation():
    text = (SRC / "previewSession.js").read_text()
    declared = re.search(r"PREVIEW_SANDBOX = '([^']+)'", text).group(1)
    assert declared == IFRAME_SANDBOX and "top-navigation" not in declared
    for path, body in _sources().items():
        assert "allow-top-navigation" not in body, path.name


def test_preview_components_use_the_session_endpoint_and_handle_503():
    api = (SRC / "api.js").read_text()
    assert "/preview-session" in api
    session = (SRC / "previewSession.js").read_text()
    assert "503" in session and "AETHER_PREVIEW_ORIGIN" in session
    for name in ("AppPreviewPanel", "ProjectLivePreviewPanel", "RunAppPanel"):
        body = (SRC / "components" / "project" / f"{name}.jsx").read_text()
        assert "previewSession" in body or "PreviewFrame" in body, name
