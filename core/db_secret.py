"""Database credentials from AWS Secrets Manager (KAN-244).

RDS rotates the master password every 7 days (managed secret). A static DATABASE_URL then goes stale and the API
loses its database (outage 28 Nov 2026). When DATABASE_SECRET_ARN is set, the username/password come from the secret
instead of the URL; the URL still supplies host, port and database name (an RDS managed secret holds only the
credentials). Unset = no behaviour change.

  DATABASE_SECRET_ARN   secret id/ARN (JSON with "username" and "password")
  AWS_REGION            region of the secret (AWS_DEFAULT_REGION also read; else boto3's own resolution)

Needs secretsmanager:GetSecretValue (+ kms:Decrypt for a customer-managed key) on that secret for the instance role.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Optional, Tuple

from sqlalchemy.engine import make_url

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cache: Optional[Tuple[str, str]] = None


def enabled() -> bool:
    return bool(os.environ.get("DATABASE_SECRET_ARN", "").strip())


def _fetch() -> Tuple[str, str]:
    import boto3  # imported here: only deployments that use the secret need AWS credentials/config

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or None
    client = boto3.client("secretsmanager", region_name=region)
    raw = client.get_secret_value(SecretId=os.environ["DATABASE_SECRET_ARN"].strip())["SecretString"]
    data = json.loads(raw)
    return data["username"], data["password"]


def credentials(refresh: bool = False) -> Tuple[str, str]:
    """(username, password), cached; refresh=True re-reads the secret (after the password was rotated)."""
    global _cache
    with _lock:
        if _cache is None or refresh:
            _cache = _fetch()
            logger.info("database credentials %s from Secrets Manager", "refreshed" if refresh else "loaded")
        return _cache


def apply_to_url(url: str) -> str:
    """The same URL with the secret's username and password."""
    user, password = credentials()
    return make_url(url).set(username=user, password=password).render_as_string(hide_password=False)


def is_auth_failure(exc: BaseException) -> bool:
    """True when PostgreSQL rejected the credentials (SQLSTATE 28P01 invalid password / 28000 invalid authorization)."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if getattr(exc, "sqlstate", None) in ("28P01", "28000"):
            return True
        if "password authentication failed" in str(exc).lower():
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def reset_for_tests() -> None:
    global _cache
    _cache = None
