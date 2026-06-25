from __future__ import annotations
import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

VAULT_ADDR = os.getenv("VAULT_ADDR", "")
VAULT_TOKEN = os.getenv("VAULT_TOKEN", "")
VAULT_MOUNT = os.getenv(
    "VAULT_MOUNT", "secret")
VAULT_ENABLED = bool(
    VAULT_ADDR and VAULT_TOKEN)

# In-memory secret cache and local store
_SECRET_CACHE: dict[str, str] = {}
_LOCAL_SECRETS: dict[str, str] = {}


@dataclass
class SecretResult:
    key: str
    value: Optional[str]
    source: str
    # "vault", "env", "local", "not_found"
    found: bool


def is_vault_enabled() -> bool:
    return VAULT_ENABLED


def set_local_secret(
    key: str, value: str
) -> None:
    """Store a secret in local in-memory store."""
    _LOCAL_SECRETS[key] = value
    _SECRET_CACHE[key] = value
    logger.debug(f"Local secret set: {key}")


def delete_local_secret(key: str) -> bool:
    removed = False
    if key in _LOCAL_SECRETS:
        del _LOCAL_SECRETS[key]
        removed = True
    if key in _SECRET_CACHE:
        del _SECRET_CACHE[key]
    return removed


def list_secret_keys() -> list[str]:
    """List all known secret keys."""
    keys = set(_LOCAL_SECRETS.keys())
    keys.update(_SECRET_CACHE.keys())
    return sorted(list(keys))


def _fetch_from_vault(
    key: str
) -> Optional[str]:
    """Attempt to fetch a secret from Vault."""
    if not VAULT_ENABLED:
        return None
    try:
        import requests
        url = (
            f"{VAULT_ADDR}/v1/"
            f"{VAULT_MOUNT}/data/{key}"
        )
        resp = requests.get(
            url,
            headers={
                "X-Vault-Token": VAULT_TOKEN
            },
            timeout=3
        )
        if resp.status_code == 200:
            data = resp.json()
            # Handle standard V2 KV store format
            value = (
                data.get("data", {})
                    .get("data", {})
                    .get("value")
            )
            if value:
                _SECRET_CACHE[key] = value
                return value
    except Exception as e:
        logger.warning(
            f"Vault fetch failed for "
            f"{key}: {e}")
    return None


def get_secret(key: str) -> SecretResult:
    """
    Fetch a secret with priority:
    1. Cache
    2. Vault (if enabled)
    3. Environment variable
    4. Local store
    """
    # 1. Cache
    if key in _SECRET_CACHE:
        return SecretResult(
            key=key,
            value=_SECRET_CACHE[key],
            source="cache",
            found=True
        )

    # 2. Vault
    if VAULT_ENABLED:
        val = _fetch_from_vault(key)
        if val:
            return SecretResult(
                key=key,
                value=val,
                source="vault",
                found=True
            )

    # 3. Environment
    env_val = os.getenv(key.upper())
    if env_val:
        _SECRET_CACHE[key] = env_val
        return SecretResult(
            key=key,
            value=env_val,
            source="env",
            found=True
        )

    # 4. Local store
    if key in _LOCAL_SECRETS:
        return SecretResult(
            key=key,
            value=_LOCAL_SECRETS[key],
            source="local",
            found=True
        )

    return SecretResult(
        key=key,
        value=None,
        source="not_found",
        found=False
    )


def rotate_secret(
    key: str,
    new_value: str
) -> bool:
    """
    Rotate a secret value.
    Updates Vault if enabled, else local.
    """
    if VAULT_ENABLED:
        try:
            import requests
            url = (
                f"{VAULT_ADDR}/v1/"
                f"{VAULT_MOUNT}/data/{key}"
            )
            resp = requests.post(
                url,
                json={"data": {
                    "value": new_value}},
                headers={
                    "X-Vault-Token": VAULT_TOKEN
                },
                timeout=3
            )
            if resp.status_code in (200, 204):
                _SECRET_CACHE[key] = new_value
                logger.info(
                    f"Rotated secret in "
                    f"Vault: {key}")
                return True
        except Exception as e:
            logger.warning(
                f"Vault rotate failed: {e}")

    # Fallback: rotate locally
    set_local_secret(key, new_value)
    logger.info(
        f"Rotated secret locally: {key}")
    return True


def clear_cache() -> None:
    _SECRET_CACHE.clear()
