"""Pattern name resolver — resolves hard-coded model names in pattern templates.

IoT and Social patterns embed hard-coded model names (Device, SensorReading,
User, Post, etc.).  When the domain IR uses different entity names, this module
performs the substitution so the generated code refers to the correct models.

Usage:
    from aether_os.phases.patterns.pattern_name_resolver import (
        generate_iot_pattern,
        generate_social_pattern,
    )
    code = generate_iot_pattern(entity_map={"device": "Sensor"})
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── IoT canonical names ────────────────────────────────────────────────────────

# Maps lowercase role → canonical class name used in the template.
# When the IR uses a different name, generate_iot_pattern() substitutes it.
_IOT_CANONICAL: dict[str, str] = {
    "device": "Device",
    "reading": "SensorReading",
    "alert": "Alert",
    "command": "Command",
}

# ── Social canonical names ─────────────────────────────────────────────────────

_SOCIAL_CANONICAL: dict[str, str] = {
    "user": "User",
    "userprofile": "UserProfile",
    "follow": "Follow",
    "post": "Post",
    "hashtag": "Hashtag",
    "posthashtag": "PostHashtag",
    "like": "Like",
    "notification": "Notification",
}


# ── Resolver functions ─────────────────────────────────────────────────────────

def generate_iot_pattern(entity_map: dict | None = None) -> str:
    """Return the IoT router code with model names resolved from entity_map.

    entity_map maps canonical role (lowercase) → actual IR entity name.
    When entity_map is None or missing a role, the canonical default is used
    (Device, SensorReading, Alert, Command) for backward compatibility.

    Example:
        entity_map = {"device": "Sensor", "reading": "Measurement"}
        # models.Sensor and models.Measurement replace the defaults.
    """
    from aether_os.phases.patterns.iot_timeseries import IOT_TIMESERIES_CODE

    if not entity_map:
        return IOT_TIMESERIES_CODE

    code = IOT_TIMESERIES_CODE
    try:
        substitutions: list[tuple[str, str]] = []
        for role, canonical_name in _IOT_CANONICAL.items():
            ir_name = entity_map.get(role)
            if ir_name and ir_name != canonical_name:
                substitutions.append((f"models.{canonical_name}", f"models.{ir_name}"))

        for old, new in substitutions:
            code = code.replace(old, new)
            logger.debug("[iot_pattern] substituted %s → %s", old, new)
    except Exception as e:
        logger.warning("[iot_pattern] entity_map substitution failed (using defaults): %s", e)
        from aether_os.phases.patterns.iot_timeseries import IOT_TIMESERIES_CODE as _fallback
        return _fallback

    return code


def generate_social_pattern(entity_map: dict | None = None) -> str:
    """Return the social router code with model names resolved from entity_map.

    entity_map maps canonical role (lowercase) → actual IR entity name.
    When entity_map is None or missing a role, the canonical default is used
    for backward compatibility.

    Example:
        entity_map = {"user": "Member", "post": "Article"}
        # models.Member and models.Article replace User and Post throughout.
    """
    from aether_os.phases.patterns.social_graph import SOCIAL_GRAPH_CODE

    if not entity_map:
        return SOCIAL_GRAPH_CODE

    code = SOCIAL_GRAPH_CODE
    try:
        # Sort by name length descending so "UserProfile" is replaced before "User".
        substitutions: list[tuple[str, str]] = []
        for role, canonical_name in sorted(
            _SOCIAL_CANONICAL.items(),
            key=lambda kv: len(kv[1]),
            reverse=True,
        ):
            ir_name = entity_map.get(role)
            if ir_name and ir_name != canonical_name:
                substitutions.append((f"models.{canonical_name}", f"models.{ir_name}"))

        for old, new in substitutions:
            code = code.replace(old, new)
            logger.debug("[social_pattern] substituted %s → %s", old, new)
    except Exception as e:
        logger.warning("[social_pattern] entity_map substitution failed (using defaults): %s", e)
        from aether_os.phases.patterns.social_graph import SOCIAL_GRAPH_CODE as _fallback
        return _fallback

    return code


__all__ = ["generate_iot_pattern", "generate_social_pattern"]
