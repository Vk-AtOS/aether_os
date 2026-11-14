"""
PasswordShield — breach detection using the HaveIBeenPwned Pwned Passwords API.

Uses k-anonymity: only the first 5 characters of the SHA-1 hash are sent to
the API. The actual password or full hash is NEVER transmitted. This is the
same method used by 1Password, Firefox Monitor, and GitHub.

Also enforces password complexity beyond the minimum length already checked
by the auth layer.

Usage:
    from aether_os.core.guardian.password_shield import check_password_safety
    ok, reason = await check_password_safety("my-password")
    if not ok:
        raise HTTPException(422, reason)
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Tuple

logger = logging.getLogger(__name__)

# Common passwords blocked even if not in HIBP (fast local check first)
_COMMON_PASSWORDS = frozenset({
    "password", "password1", "password123", "123456", "12345678", "qwerty",
    "abc123", "111111", "iloveyou", "admin", "admin123", "letmein",
    "welcome", "monkey", "dragon", "master", "superman", "batman",
    "passw0rd", "p@ssword", "p@ssw0rd", "demo1234", "test1234",
    "changeme", "secret", "login", "access", "shadow", "sunshine",
})

# Minimum complexity requirements
_MIN_LENGTH = 10


def _sha1(password: str) -> str:
    return hashlib.sha1(password.encode("utf-8"), usedforsecurity=False).hexdigest().upper()


def _check_complexity(password: str) -> Tuple[bool, str]:
    """Fast local checks before hitting the network."""
    if len(password) < _MIN_LENGTH:
        return False, f"Password must be at least {_MIN_LENGTH} characters."

    if password.lower() in _COMMON_PASSWORDS:
        return False, "This password is too common. Please choose a more unique password."

    # Require at least 3 of: uppercase, lowercase, digit, special char
    checks = [
        bool(re.search(r"[A-Z]", password)),
        bool(re.search(r"[a-z]", password)),
        bool(re.search(r"\d", password)),
        bool(re.search(r"[^A-Za-z0-9]", password)),
    ]
    if sum(checks) < 3:
        return False, (
            "Password must contain at least 3 of: uppercase letters, lowercase letters, "
            "numbers, and special characters (!@#$%^&* etc.)."
        )

    # Reject passwords that are just the same character repeated
    if len(set(password)) < 4:
        return False, "Password is too repetitive. Please choose a more varied password."

    return True, ""


async def _check_hibp(password: str) -> Tuple[bool, int]:
    """
    Check against HIBP Pwned Passwords via k-anonymity.
    Returns (is_pwned, breach_count).
    Fails open — if HIBP is unreachable, returns (False, 0) to never block signup.
    """
    sha1 = _sha1(password)
    prefix = sha1[:5]
    suffix = sha1[5:]

    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"https://api.pwnedpasswords.com/range/{prefix}",
                headers={
                    "Add-Padding": "true",   # prevents traffic analysis via response size
                    "User-Agent": "AetherOS-PasswordShield/1.0",
                },
            )
            if resp.status_code != 200:
                logger.warning("HIBP API returned %d — failing open", resp.status_code)
                return False, 0

            for line in resp.text.splitlines():
                if ":" not in line:
                    continue
                hash_suffix, count_str = line.split(":", 1)
                if hash_suffix.strip() == suffix:
                    count = int(count_str.strip())
                    return True, count

        return False, 0

    except ImportError:
        # httpx not installed — skip HIBP check, still enforce local rules
        logger.warning("PasswordShield: httpx not installed — HIBP check skipped")
        return False, 0
    except Exception as exc:
        # Network error, HIBP down, timeout — always fail open
        logger.warning("PasswordShield: HIBP check failed (%s) — failing open", exc)
        return False, 0


async def check_password_safety(password: str) -> Tuple[bool, str]:
    """
    Full password safety check. Returns (is_safe, rejection_reason).
    rejection_reason is empty string when safe.

    Checks (in order):
      1. Local complexity rules (fast)
      2. Common password list (fast)
      3. HIBP k-anonymity breach check (network, ~100ms)
    """
    ok, reason = _check_complexity(password)
    if not ok:
        return False, reason

    is_pwned, breach_count = await _check_hibp(password)
    if is_pwned:
        # Be transparent — tell the user how many breaches so they understand the risk
        count_str = f"{breach_count:,}" if breach_count > 0 else "many"
        return False, (
            f"This password has appeared in {count_str} known data breach"
            f"{'es' if breach_count != 1 else ''}. "
            "It is not safe to use. Please choose a different password."
        )

    return True, ""
