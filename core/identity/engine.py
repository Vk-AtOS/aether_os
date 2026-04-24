"""
Aether-One Identity & Permissions Engine

Local-first, zero-trust identity and token layer that sits on top of:

- Org configuration and RBAC (aetherone.org_config)
- Risk- and environment-aware operation evaluation

Goals
-----

- Never persist raw tokens; only hashed identifiers on disk.
- Enforce least privilege via explicit scopes on tokens.
- Compose with org_config's evaluate_operation instead of bypassing it.
- Work fully offline in the project directory (.aether-one/identity_store.json).

Intended usages
---------------

1. CLI / local developer:
    - Create principals with roles
    - Issue short-lived tokens for automation scripts
    - Validate tokens + scopes before executing operations

2. Orchestrator:
    - Validate any presented token on API calls
    - Pass validated principal + roles into org_config.evaluate_operation()
"""

from __future__ import annotations

import json
import logging
import os
import hashlib
import secrets
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from .org_config import (
    OrgConfig,
    OrgDecision,
    evaluate_operation,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    """Return current UTC time (separated for testability)."""
    return datetime.now(timezone.utc)


@dataclass
class Principal:
    """
    A principal is either a human user or a service account.

    Roles here are "identity roles" and map to org_config roles.
    """

    user_id: str
    display_name: str
    roles: List[str]
    is_service: bool = False
    created_at: str = ""
    last_updated_at: str = ""


@dataclass
class TokenRecord:
    """
    Stored record for an access token.

    Only the hash identifier is stored; the raw token string is never persisted.
    """

    token_id: str
    token_prefix: str
    principal_id: str
    scopes: List[str]
    issued_at: str
    expires_at: Optional[str]
    revoked: bool = False
    last_used_at: Optional[str] = None
    description: Optional[str] = None


@dataclass
class IdentityDecision:
    """
    Result of validating a token and evaluating permission for an operation.
    """

    allowed: bool
    requires_approval: bool
    denied: bool
    principal_id: Optional[str]
    token_id: Optional[str]
    scopes_checked: List[str]
    reasons: List[str]
    org_decision: Optional[OrgDecision] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# Identity store
# ---------------------------------------------------------------------------


class IdentityStore:
    """
    Local JSON-backed identity store.

    Layout on disk (inside project):

        .aether-one/identity_store.json

    Structure:

        {
          "version": 1,
          "principals": { "<user_id>": { ...Principal... }, ... },
          "tokens": { "<token_id>": { ...TokenRecord... }, ... }
        }
    """

    VERSION = 1

    def __init__(
        self,
        path: str,
        *,
        principals: Optional[Dict[str, Principal]] = None,
        tokens: Optional[Dict[str, TokenRecord]] = None,
        now_fn: Callable[[], datetime] = _now_utc,
    ) -> None:
        self.path = path
        self._principals: Dict[str, Principal] = principals or {}
        self._tokens: Dict[str, TokenRecord] = tokens or {}
        self._now_fn = now_fn

    # ---- Construction / persistence -------------------------------------------------

    @classmethod
    def _store_path(cls, project_path: str, filename: str = "identity_store.json") -> str:
        project_root = os.path.abspath(os.path.expanduser(project_path))
        meta_dir = os.path.join(project_root, ".aether-one")
        os.makedirs(meta_dir, exist_ok=True)
        return os.path.join(meta_dir, filename)

    @classmethod
    def load(
        cls,
        project_path: str,
        *,
        filename: str = "identity_store.json",
        now_fn: Callable[[], datetime] = _now_utc,
    ) -> "IdentityStore":
        """
        Load or create an IdentityStore for the given project path.
        """
        store_path = cls._store_path(project_path, filename)
        if not os.path.exists(store_path):
            logger.info("Creating new identity store at %s", store_path)
            store = cls(store_path, now_fn=now_fn)
            store._save()
            return store

        try:
            with open(store_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError as exc:
            logger.error("Identity store at %s is corrupted: %s", store_path, exc)
            raise

        version = raw.get("version", 0)
        if version != cls.VERSION:
            logger.warning(
                "Identity store version mismatch: expected %s, got %s",
                cls.VERSION,
                version,
            )

        principals: Dict[str, Principal] = {}
        for uid, pdata in raw.get("principals", {}).items():
            principals[uid] = Principal(
                user_id=pdata["user_id"],
                display_name=pdata["display_name"],
                roles=list(pdata.get("roles", [])),
                is_service=bool(pdata.get("is_service", False)),
                created_at=pdata.get("created_at", ""),
                last_updated_at=pdata.get("last_updated_at", ""),
            )

        tokens: Dict[str, TokenRecord] = {}
        for tid, tdata in raw.get("tokens", {}).items():
            tokens[tid] = TokenRecord(
                token_id=tdata["token_id"],
                token_prefix=tdata.get("token_prefix", "") or tdata["token_id"][:8],
                principal_id=tdata["principal_id"],
                scopes=list(tdata.get("scopes", [])),
                issued_at=tdata["issued_at"],
                expires_at=tdata.get("expires_at"),
                revoked=bool(tdata.get("revoked", False)),
                last_used_at=tdata.get("last_used_at"),
                description=tdata.get("description"),
            )

        return cls(store_path, principals=principals, tokens=tokens, now_fn=now_fn)

    def _save(self) -> None:
        """
        Persist identity store to disk atomically.
        """
        data = {
            "version": self.VERSION,
            "principals": {uid: asdict(p) for uid, p in self._principals.items()},
            "tokens": {tid: asdict(t) for tid, t in self._tokens.items()},
        }
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp_path, self.path)
        logger.debug("Identity store saved to %s", self.path)

    def _now(self) -> datetime:
        return self._now_fn()

    # ---- Principal management -------------------------------------------------------

    def list_principals(self) -> List[Principal]:
        return list(self._principals.values())

    def get_principal(self, user_id: str) -> Optional[Principal]:
        return self._principals.get(user_id)

    def create_or_update_principal(
        self,
        user_id: str,
        display_name: str,
        roles: List[str],
        *,
        is_service: bool = False,
    ) -> Principal:
        """
        Create or update a principal with the given roles.

        Idempotent: calling this again with the same user_id will update
        display_name and roles.
        """
        now_iso = self._now().isoformat()
        existing = self._principals.get(user_id)
        if existing:
            existing.display_name = display_name
            existing.roles = list(sorted(set(roles)))
            existing.is_service = bool(is_service)
            existing.last_updated_at = now_iso
            principal = existing
            logger.info("Updated principal %s", user_id)
        else:
            principal = Principal(
                user_id=user_id,
                display_name=display_name,
                roles=list(sorted(set(roles))),
                is_service=bool(is_service),
                created_at=now_iso,
                last_updated_at=now_iso,
            )
            self._principals[user_id] = principal
            logger.info("Created principal %s", user_id)

        self._save()
        return principal

    # ---- Token management -----------------------------------------------------------

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _token_prefix(token: str) -> str:
        return token[:8]

    def issue_token(
        self,
        principal_id: str,
        scopes: List[str],
        *,
        ttl_minutes: Optional[int] = 60,
        description: Optional[str] = None,
    ) -> str:
        """
        Issue a new token for the given principal.

        Returns the **raw token string**; only its hash is stored.

        Scopes are simple strings like:
            - "operation:guarded_python_fix"
            - "operation:*"
            - "env:dev"
        """
        if principal_id not in self._principals:
            raise ValueError(f"Unknown principal {principal_id!r}")

        raw_token = secrets.token_urlsafe(32)
        token_id = self._hash_token(raw_token)
        now = self._now()
        issued_at = now.isoformat()
        expires_at: Optional[str]
        if ttl_minutes is None:
            expires_at = None
        else:
            expires_at = (now + timedelta(minutes=ttl_minutes)).isoformat()

        record = TokenRecord(
            token_id=token_id,
            token_prefix=self._token_prefix(raw_token),
            principal_id=principal_id,
            scopes=list(sorted(set(scopes))),
            issued_at=issued_at,
            expires_at=expires_at,
            revoked=False,
            last_used_at=None,
            description=description,
        )
        self._tokens[token_id] = record
        self._save()

        logger.info(
            "Issued new token for principal %s (prefix=%s, ttl_minutes=%s)",
            principal_id,
            record.token_prefix,
            ttl_minutes,
        )
        return raw_token

    def _lookup_token(self, raw_token: str) -> Tuple[Optional[TokenRecord], Optional[Principal], List[str]]:
        reasons: List[str] = []
        token_id = self._hash_token(raw_token)
        record = self._tokens.get(token_id)
        if not record:
            reasons.append("Unknown or invalid token.")
            return None, None, reasons

        principal = self._principals.get(record.principal_id)
        if not principal:
            reasons.append(f"Principal {record.principal_id!r} not found.")
            return None, None, reasons

        return record, principal, reasons

    def revoke_token(self, raw_token: str) -> bool:
        """
        Revoke a token by its raw value.

        Returns True if the token existed and was revoked.
        """
        record, _, _ = self._lookup_token(raw_token)
        if not record:
            logger.warning("Attempted to revoke unknown token.")
            return False
        if record.revoked:
            logger.info("Token %s already revoked.", record.token_prefix)
            return True

        record.revoked = True
        self._save()
        logger.info("Revoked token for principal %s (prefix=%s)", record.principal_id, record.token_prefix)
        return True

    # ---- Permission evaluation ------------------------------------------------------

    @staticmethod
    def _scopes_allow_operation(
        scopes: List[str],
        *,
        operation_type: str,
        environment: str,
    ) -> Tuple[bool, List[str]]:
        """
        Simple least-privilege scope model:

        - 'operation:*'                 -> all operations
        - f'operation:{operation_type}' -> just that operation
        - 'env:<environment>'          -> hint, not enforced as hard requirement
        """
        matched: List[str] = []
        for scope in scopes:
            if scope == "operation:*":
                matched.append(scope)
            elif scope.startswith("operation:") and scope.split(":", 1)[1] == operation_type:
                matched.append(scope)

        if not matched:
            return False, matched

        # environment scopes are advisory; we don't fail if missing but record them.
        env_scope = f"env:{environment}"
        if env_scope in scopes:
            matched.append(env_scope)

        return True, matched

    def evaluate_token_permission(
        self,
        raw_token: str,
        *,
        org_config: OrgConfig,
        operation_type: str,
        environment: str,
        risk_level: str,
        is_guarded: bool,
    ) -> IdentityDecision:
        """
        Validate a token, check scopes, then call org_config.evaluate_operation.

        Order of checks (fail-fast):

        1. Token exists and principal is known.
        2. Token is not revoked and (if expires_at set) is not expired.
        3. Token scopes allow the requested operation.
        4. org_config.evaluate_operation approves, denies, or requires approval.

        The strictest result wins. Identity layer can only make the decision
        *more restrictive* than org_config, never less.
        """
        reasons: List[str] = []
        record, principal, initial_reasons = self._lookup_token(raw_token)
        reasons.extend(initial_reasons)

        if record is None or principal is None:
            logger.warning("Token validation failed: %s", "; ".join(reasons))
            return IdentityDecision(
                allowed=False,
                requires_approval=False,
                denied=True,
                principal_id=None if principal is None else principal.user_id,
                token_id=None if record is None else record.token_id,
                scopes_checked=[],
                reasons=reasons,
                org_decision=None,
            )

        now = self._now()
        if record.revoked:
            reasons.append("Token is revoked.")
        if record.expires_at is not None:
            try:
                exp = datetime.fromisoformat(record.expires_at)
            except ValueError:
                reasons.append("Token expiry timestamp is invalid.")
            else:
                if now >= exp:
                    reasons.append("Token has expired.")

        scopes_ok, matched_scopes = self._scopes_allow_operation(
            record.scopes,
            operation_type=operation_type,
            environment=environment,
        )
        if not scopes_ok:
            reasons.append("Token scopes do not permit this operation.")

        # If any hard errors so far, deny without calling org_config.
        if reasons and (
            "Unknown or invalid token." in reasons
            or "Principal" in " ".join(reasons)
            or "revoked" in " ".join(reasons)
            or "expired" in " ".join(reasons)
            or "do not permit" in " ".join(reasons)
        ):
            logger.info(
                "Identity check denied for principal=%s op=%s env=%s: %s",
                principal.user_id,
                operation_type,
                environment,
                "; ".join(reasons),
            )
            return IdentityDecision(
                allowed=False,
                requires_approval=False,
                denied=True,
                principal_id=principal.user_id,
                token_id=record.token_id,
                scopes_checked=matched_scopes,
                reasons=reasons,
                org_decision=None,
            )

        # Delegate to org_config
        org_dec = evaluate_operation(
            org_config,
            user_id=principal.user_id,
            user_roles=principal.roles,
            operation_type=operation_type,
            risk_level=risk_level,
            environment=environment,
            is_guarded=is_guarded,
        )

        # Combine decisions: identity layer cannot be more permissive than org_config.
        allowed = org_dec.allowed
        requires_approval = org_dec.requires_approval
        denied = org_dec.denied

        reasons.extend(org_dec.reasons)

        record.last_used_at = now.isoformat()
        self._save()

        logger.info(
            "Identity+org decision for principal=%s op=%s env=%s -> allowed=%s requires_approval=%s denied=%s",
            principal.user_id,
            operation_type,
            environment,
            allowed,
            requires_approval,
            denied,
        )

        return IdentityDecision(
            allowed=allowed,
            requires_approval=requires_approval,
            denied=denied,
            principal_id=principal.user_id,
            token_id=record.token_id,
            scopes_checked=matched_scopes,
            reasons=reasons,
            org_decision=org_dec,
        )

