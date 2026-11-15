"""Input validation for the p03 scaffold: project names become directory names and
github_url is handed to `git clone`, so both come from an untrusted request."""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}")
_DEFAULT_HOSTS = "github.com,gitlab.com,bitbucket.org"


def is_valid_project_name(name: str) -> bool:
    return bool(_NAME_RE.fullmatch(name)) and ".." not in name


def safe_project_name(name: str) -> str:
    """Coerce any (e.g. LLM-chosen) name into a single safe path component."""
    cleaned = re.sub(r"[^A-Za-z0-9 _.-]", "-", str(name or "")).strip(" .-")[:64].strip(" .-")
    return cleaned.replace("..", ".") or "app"


def validate_clone_url(url: str) -> str:
    """Return url if it is an https URL on an allowed host; raise ValueError otherwise.

    Hosts come from GIT_CLONE_ALLOWED_HOSTS (comma separated). Anything else
    (file://, ssh, local paths, credentials in the URL, odd ports, leading '-')
    is refused so the clone cannot read host repositories or internal services.
    """
    url = (url or "").strip()
    if not url or url.startswith("-") or any(c.isspace() or ord(c) < 32 for c in url):
        raise ValueError("invalid git URL")
    parts = urlsplit(url)
    allowed = {h.strip().lower() for h in os.environ.get("GIT_CLONE_ALLOWED_HOSTS", _DEFAULT_HOSTS).split(",") if h.strip()}
    try:
        port = parts.port
    except ValueError:
        raise ValueError("invalid git URL port") from None
    if parts.scheme != "https" or "@" in parts.netloc or port not in (None, 443):
        raise ValueError("only plain https:// git URLs are allowed")
    if (parts.hostname or "").lower() not in allowed:
        raise ValueError("git host is not on the allow-list")
    return url
