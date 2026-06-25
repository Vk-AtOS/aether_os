from __future__ import annotations
import logging
import os
from dataclasses import dataclass, field
from typing import Optional
import requests
from requests.exceptions import (
    RequestException, Timeout, ConnectionError
)
from src.federation.anonymizer import (
    AnonymizedPattern,
    create_anonymized_pattern,
    is_safe_to_share,
    anonymize_repo_name
)

logger = logging.getLogger(__name__)

REGISTRY_URL = os.getenv(
    "FEDERATION_REGISTRY_URL", "")
REGISTRY_API_KEY = os.getenv(
    "FEDERATION_API_KEY", "")
REGISTRY_TIMEOUT = int(os.getenv(
    "FEDERATION_TIMEOUT", "5"))
REGISTRY_ENABLED = bool(
    os.getenv("FEDERATION_ENABLED", ""))

@dataclass
class RegistrySubmitResult:
    success: bool
    pattern_id: Optional[str] = None
    error: Optional[str] = None
    skipped: bool = False
    skip_reason: Optional[str] = None

@dataclass
class SharedPattern:
    pattern_id: str
    error_type: str
    language: str
    patch_template: str
    success_count: int = 0
    confidence: float = 0.0
    source_hash: str = ""

@dataclass
class RegistryPullResult:
    success: bool
    patterns: list[SharedPattern] = \
        field(default_factory=list)
    error: Optional[str] = None
    skipped: bool = False

def is_registry_enabled() -> bool:
    """Check if federation registry is configured."""
    return bool(REGISTRY_URL and REGISTRY_ENABLED)

def _get_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if REGISTRY_API_KEY:
        headers["X-API-Key"] = REGISTRY_API_KEY
    return headers

def submit_pattern(
    pattern: AnonymizedPattern
) -> RegistrySubmitResult:
    """
    Submit an anonymized pattern to the registry.
    Returns RegistrySubmitResult.
    Gracefully handles offline registry.
    """
    if not is_registry_enabled():
        return RegistrySubmitResult(
            success=False,
            skipped=True,
            skip_reason="Federation not enabled"
        )

    if not is_safe_to_share(pattern):
        return RegistrySubmitResult(
            success=False,
            skipped=True,
            skip_reason="Pattern failed safety check"
        )

    payload = {
        "fingerprint": pattern.anonymized_fingerprint,
        "error_type": pattern.error_type,
        "language": pattern.language,
        "patch_template": pattern.patch_template,
        "log_snippet": pattern.anonymized_log,
    }

    try:
        resp = requests.post(
            f"{REGISTRY_URL}/api/patterns",
            json=payload,
            headers=_get_headers(),
            timeout=REGISTRY_TIMEOUT
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            return RegistrySubmitResult(
                success=True,
                pattern_id=data.get("id")
            )
        else:
            return RegistrySubmitResult(
                success=False,
                error=(
                    f"Registry returned "
                    f"{resp.status_code}"
                )
            )
    except (Timeout, ConnectionError) as e:
        logger.warning(
            f"Registry unreachable: {e}")
        return RegistrySubmitResult(
            success=False,
            error=f"Registry unreachable: {e}"
        )
    except RequestException as e:
        logger.warning(
            f"Registry request failed: {e}")
        return RegistrySubmitResult(
            success=False,
            error=str(e)
        )

def pull_patterns(
    error_type: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = 20
) -> RegistryPullResult:
    """
    Pull shared patterns from the registry.
    Returns RegistryPullResult with pattern list.
    """
    if not is_registry_enabled():
        return RegistryPullResult(
            success=False,
            skipped=True
        )

    params: dict = {"limit": limit}
    if error_type:
        params["error_type"] = error_type
    if language:
        params["language"] = language

    try:
        resp = requests.get(
            f"{REGISTRY_URL}/api/patterns",
            params=params,
            headers=_get_headers(),
            timeout=REGISTRY_TIMEOUT
        )
        if resp.status_code == 200:
            data = resp.json()
            patterns = [
                SharedPattern(
                    pattern_id=p.get("id", ""),
                    error_type=p.get(
                        "error_type", ""),
                    language=p.get(
                        "language", ""),
                    patch_template=p.get(
                        "patch_template", ""),
                    success_count=p.get(
                        "success_count", 0),
                    confidence=p.get(
                        "confidence", 0.0),
                    source_hash=p.get(
                        "source_hash", "")
                )
                for p in data.get("patterns", [])
            ]
            return RegistryPullResult(
                success=True,
                patterns=patterns
            )
        else:
            return RegistryPullResult(
                success=False,
                error=(
                    f"Registry returned "
                    f"{resp.status_code}"
                )
            )
    except (Timeout, ConnectionError) as e:
        logger.warning(
            f"Registry unreachable: {e}")
        return RegistryPullResult(
            success=False,
            error=f"Registry unreachable: {e}"
        )
    except RequestException as e:
        return RegistryPullResult(
            success=False,
            error=str(e)
        )

def submit_repair_result(
    fingerprint: str,
    error_type: str,
    language: str,
    patch_diff: str,
    log_snippet: str,
    repo_name: Optional[str] = None
) -> RegistrySubmitResult:
    """
    Convenience wrapper: anonymize then submit.
    Call this from the pipeline after a repair.
    """
    if not is_registry_enabled():
        return RegistrySubmitResult(
            success=False,
            skipped=True,
            skip_reason="Federation not enabled"
        )

    try:
        pattern = create_anonymized_pattern(
            fingerprint=fingerprint,
            error_type=error_type,
            language=language,
            patch_diff=patch_diff,
            log_snippet=log_snippet,
            repo_name=repo_name
        )
        return submit_pattern(pattern)
    except Exception as e:
        logger.warning(
            f"submit_repair_result failed: {e}")
        return RegistrySubmitResult(
            success=False,
            error=str(e)
        )
