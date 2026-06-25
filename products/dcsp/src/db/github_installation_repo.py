"""DB helpers for GitHubInstallation records."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def upsert_installation(
    db: Any,
    installation_id: int,
    account_login: str,
    account_type: str,
    tenant_id: str | None = None,
) -> None:
    """Insert or reactivate a GitHubInstallation row."""
    from src.models import GitHubInstallation
    existing = (
        db.query(GitHubInstallation)
        .filter(GitHubInstallation.installation_id == installation_id)
        .first()
    )
    if existing:
        existing.is_active = True
        existing.account_login = account_login
        existing.account_type = account_type
        if tenant_id:
            existing.tenant_id = tenant_id
    else:
        record = GitHubInstallation(
            installation_id=installation_id,
            account_login=account_login,
            account_type=account_type,
            tenant_id=tenant_id,
        )
        db.add(record)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("upsert_installation commit failed: %s", e)
        raise


def deactivate_installation(db: Any, installation_id: int) -> None:
    """Mark a GitHubInstallation as inactive (uninstalled)."""
    from src.models import GitHubInstallation
    record = (
        db.query(GitHubInstallation)
        .filter(GitHubInstallation.installation_id == installation_id)
        .first()
    )
    if record:
        record.is_active = False
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error("deactivate_installation commit failed: %s", e)
            raise
    else:
        logger.warning(
            "deactivate_installation: installation_id %s not found", installation_id
        )
