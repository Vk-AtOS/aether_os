"""
Aether-One Automated Licensing System

Local-first, zero-trust licensing for SaaS / enterprise deployments.

Design goals
------------

- No online calls required to validate a license.
- All license data lives in the project directory:
    .aether-one/license.token
- License tokens are signed with HMAC-SHA256 using a shared secret:
    - Prefer env var AETHERONE_LICENSE_SECRET
    - For tests / offline tools you can pass an explicit secret.
- License payloads are human-inspectable JSON, wrapped in a compact token.

Token format
------------

    base64url(JSON payload) + "." + base64url(HMAC-SHA256 signature)

Where payload is a JSON object with at minimum:

    {
      "license_id": "LIC-XXXX",
      "license_name": "Aether-One Pro",
      "license_type": "trial|team|enterprise|node-locked",
      "customer": "Acme Corp",
      "issued_at": "ISO-8601 UTC",
      "expires_at": "ISO-8601 UTC or null",
      "max_users": 10,
      "max_projects": 5,
      "allowed_features": ["core", "enterprise", "iot", "firmware"],
      "host_binding": "optional host id (node-locked)"
    }

This module does *not* enforce user/project counts directly; that is left to
higher layers. It focuses on cryptographic validity + feature gating.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    """Return current UTC timestamp (factored out for tests)."""
    return datetime.now(timezone.utc)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data_str: str) -> bytes:
    padding = "=" * (-len(data_str) % 4)
    return base64.urlsafe_b64decode(data_str + padding)


def _canonical_json(obj: Dict[str, Any]) -> str:
    """
    Canonical JSON representation for signing:
    - sort_keys=True
    - no extra whitespace except single spaces after colons/commas.
    """
    return json.dumps(obj, separators=(",", ":"), sort_keys=True)


def _resolve_license_secret(explicit_secret: Optional[str] = None) -> str:
    """
    Resolve the HMAC secret used for signing/verification.

    Order:
        1. explicit_secret argument
        2. AETHERONE_LICENSE_SECRET env var

    Raises ValueError if no secret is available.
    """
    if explicit_secret:
        return explicit_secret
    env_secret = os.environ.get("AETHERONE_LICENSE_SECRET")
    if env_secret:
        return env_secret
    raise ValueError(
        "No license secret provided. Set AETHERONE_LICENSE_SECRET or pass explicit_secret."
    )


def _host_fingerprint() -> str:
    """
    Very lightweight host fingerprint for node-locked licenses.

    This is *not* meant as strong anti-tamper, just a basic guard:
    - hostname
    - os name
    """
    import platform

    parts = [
        platform.node() or "unknown-node",
        platform.system() or "unknown-os",
    ]
    raw = "|".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class LicensePayload:
    """
    Parsed license payload.

    Note: All timestamps are ISO 8601 strings in UTC.
    """

    license_id: str
    license_name: str
    license_type: str  # trial, team, enterprise, node-locked, etc.
    customer: str
    issued_at: str
    expires_at: Optional[str]
    max_users: Optional[int]
    max_projects: Optional[int]
    allowed_features: List[str]
    host_binding: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class LicenseValidationResult:
    """
    Outcome of verifying a license token.

    valid:
        True only if signature, expiry, and host binding all pass.
    """

    valid: bool
    expired: bool
    signature_ok: bool
    host_mismatch: bool
    reason: Optional[str]
    payload: Optional[LicensePayload]

    def requires_feature(self, feature: str) -> bool:
        """
        Return True if this license both:
        - is valid, and
        - includes the given feature
        """
        if not self.valid or not self.payload:
            return False
        return feature in self.payload.allowed_features


class LicenseError(RuntimeError):
    """Raised when license enforcement fails."""


# ---------------------------------------------------------------------------
# Core signing / verification
# ---------------------------------------------------------------------------


def sign_license_payload(
    payload: LicensePayload,
    *,
    explicit_secret: Optional[str] = None,
) -> str:
    """
    Create a signed license token from a payload.

    Returns:
        license_token: base64url(json) + "." + base64url(signature)
    """
    secret = _resolve_license_secret(explicit_secret)
    payload_dict = asdict(payload)
    json_str = _canonical_json(payload_dict)
    json_bytes = json_str.encode("utf-8")

    sig = hmac.new(secret.encode("utf-8"), json_bytes, hashlib.sha256).digest()

    token = f"{_b64url_encode(json_bytes)}.{_b64url_encode(sig)}"
    logger.info("Generated license token for %s (%s)", payload.license_id, payload.license_name)
    return token


def _parse_token(token: str) -> Tuple[Dict[str, Any], bytes]:
    """
    Split and decode a token into (payload_dict, signature_bytes).

    Raises ValueError if token structure is invalid.
    """
    try:
        payload_b64, sig_b64 = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("Invalid license token format; expected 'payload.signature'.") from exc

    try:
        payload_bytes = _b64url_decode(payload_b64)
        sig_bytes = _b64url_decode(sig_b64)
    except (base64.binascii.Error, ValueError) as exc:
        raise ValueError("Invalid base64 encoding in license token.") from exc

    try:
        payload_dict = json.loads(payload_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("License payload is not valid JSON.") from exc

    return payload_dict, sig_bytes


def verify_license_token(
    token: str,
    *,
    explicit_secret: Optional[str] = None,
    now_fn: Callable[[], datetime] = _now_utc,
    enforce_host_binding: bool = True,
) -> LicenseValidationResult:
    """
    Verify a license token's signature, expiry, and host binding.

    This function does not raise on invalid tokens; it returns a structured
    LicenseValidationResult with reason text for logging or UI.

    Signature is verified using HMAC-SHA256 over the canonical JSON payload.
    """
    try:
        payload_dict, sig_bytes = _parse_token(token)
    except ValueError as exc:
        logger.warning("Failed to parse license token: %s", exc)
        return LicenseValidationResult(
            valid=False,
            expired=False,
            signature_ok=False,
            host_mismatch=False,
            reason=str(exc),
            payload=None,
        )

    # Canonicalise and re-sign payload
    try:
        payload = LicensePayload(
            license_id=payload_dict["license_id"],
            license_name=payload_dict["license_name"],
            license_type=payload_dict["license_type"],
            customer=payload_dict["customer"],
            issued_at=payload_dict["issued_at"],
            expires_at=payload_dict.get("expires_at"),
            max_users=payload_dict.get("max_users"),
            max_projects=payload_dict.get("max_projects"),
            allowed_features=list(payload_dict.get("allowed_features", [])),
            host_binding=payload_dict.get("host_binding"),
            metadata=payload_dict.get("metadata"),
        )
    except KeyError as exc:
        msg = f"Missing required field in license payload: {exc}"
        logger.warning(msg)
        return LicenseValidationResult(
            valid=False,
            expired=False,
            signature_ok=False,
            host_mismatch=False,
            reason=msg,
            payload=None,
        )

    try:
        secret = _resolve_license_secret(explicit_secret)
    except ValueError as exc:
        logger.warning("License secret unavailable: %s", exc)
        return LicenseValidationResult(
            valid=False,
            expired=False,
            signature_ok=False,
            host_mismatch=False,
            reason=str(exc),
            payload=None,
        )

    json_str = _canonical_json(asdict(payload))
    json_bytes = json_str.encode("utf-8")
    expected_sig = hmac.new(secret.encode("utf-8"), json_bytes, hashlib.sha256).digest()

    signature_ok = hmac.compare_digest(expected_sig, sig_bytes)
    if not signature_ok:
        logger.warning("License signature mismatch for %s", payload.license_id)
        return LicenseValidationResult(
            valid=False,
            expired=False,
            signature_ok=False,
            host_mismatch=False,
            reason="Invalid license signature.",
            payload=None,
        )

    # Check expiry
    expired = False
    reason: Optional[str] = None
    now = now_fn()
    if payload.expires_at is not None:
        try:
            exp_dt = datetime.fromisoformat(payload.expires_at)
        except ValueError:
            reason = "Invalid expires_at timestamp in payload."
            logger.warning(reason)
            return LicenseValidationResult(
                valid=False,
                expired=False,
                signature_ok=True,
                host_mismatch=False,
                reason=reason,
                payload=None,
            )

        if now >= exp_dt:
            expired = True
            reason = "License has expired."

    # Host binding (for node-locked / strict deployments)
    host_mismatch = False
    if enforce_host_binding and payload.host_binding:
        local_fp = _host_fingerprint()
        if local_fp != payload.host_binding:
            host_mismatch = True
            reason = "License is bound to a different host."

    valid = signature_ok and not expired and not host_mismatch

    if valid:
        logger.info(
            "License %s (%s) validated for customer %s.",
            payload.license_id,
            payload.license_name,
            payload.customer,
        )

    return LicenseValidationResult(
        valid=valid,
        expired=expired,
        signature_ok=signature_ok,
        host_mismatch=host_mismatch,
        reason=reason,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Local project integration
# ---------------------------------------------------------------------------


def _license_file_path(project_path: str, filename: str = "license.token") -> str:
    project_root = os.path.abspath(os.path.expanduser(project_path))
    meta_dir = os.path.join(project_root, ".aether-one")
    os.makedirs(meta_dir, exist_ok=True)
    return os.path.join(meta_dir, filename)


def load_license_token_from_project(project_path: str) -> Optional[str]:
    """
    Load a license token from the project (.aether-one/license.token).

    Returns None if the file does not exist.
    """
    path = _license_file_path(project_path)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            token = f.read().strip()
        return token or None
    except OSError as exc:
        logger.error("Failed to read license token from %s: %s", path, exc)
        return None


def save_license_token_to_project(project_path: str, token: str) -> str:
    """
    Persist a license token to the project (.aether-one/license.token).

    Returns the path that was written.
    """
    path = _license_file_path(project_path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(token.strip() + "\n")
    os.replace(tmp, path)
    logger.info("License token saved to %s", path)
    return path


class LicenseManager:
    """
    High-level interface used by orchestrator / CLI to enforce licensing.

    Typical usage:

        mgr = LicenseManager.for_project(".")
        result = mgr.validate()
        mgr.enforce_feature("enterprise")  # raises LicenseError if not valid

    This class only caches the last validation result; it does not hold any
    long-lived secrets.
    """

    def __init__(
        self,
        project_path: str,
        *,
        explicit_secret: Optional[str] = None,
        now_fn: Callable[[], datetime] = _now_utc,
    ) -> None:
        self.project_path = os.path.abspath(os.path.expanduser(project_path))
        self.explicit_secret = explicit_secret
        self._now_fn = now_fn
        self._last_result: Optional[LicenseValidationResult] = None

    @classmethod
    def for_project(
        cls,
        project_path: str,
        *,
        explicit_secret: Optional[str] = None,
        now_fn: Callable[[], datetime] = _now_utc,
    ) -> "LicenseManager":
        return cls(project_path, explicit_secret=explicit_secret, now_fn=now_fn)

    def validate(self) -> LicenseValidationResult:
        """
        Validate the project's license token (if any).

        Order:
            1. AETHERONE_LICENSE_TOKEN env var
            2. .aether-one/license.token file

        Returns a LicenseValidationResult even if no license is present.
        """
        env_token = os.environ.get("AETHERONE_LICENSE_TOKEN")
        token_source = "env"
        token = env_token
        if not token:
            token = load_license_token_from_project(self.project_path)
            token_source = "file"

        if not token:
            reason = "No license token found in env or project."
            logger.warning(reason)
            result = LicenseValidationResult(
                valid=False,
                expired=False,
                signature_ok=False,
                host_mismatch=False,
                reason=reason,
                payload=None,
            )
            self._last_result = result
            return result

        logger.debug("Validating license token from %s.", token_source)
        result = verify_license_token(
            token,
            explicit_secret=self.explicit_secret,
            now_fn=self._now_fn,
            enforce_host_binding=True,
        )
        self._last_result = result
        return result

    def enforce_feature(self, feature: str) -> LicenseValidationResult:
        """
        Validate the license and enforce that 'feature' is allowed.

        Raises LicenseError if:
            - license is invalid / expired / mismatched, or
            - feature is not present in allowed_features.
        """
        result = self.validate()
        if not result.valid:
            raise LicenseError(
                f"License invalid or expired: {result.reason or 'no details'}"
            )
        if not result.requires_feature(feature):
            raise LicenseError(
                f"License for {result.payload.customer if result.payload else '?'} "
                f"does not include feature '{feature}'."
            )
        return result

