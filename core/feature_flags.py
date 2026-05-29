"""AetherOS platform feature flags backed by GrowthBook SDK.

Usage:
    from aether_os.core.feature_flags import flags
    if flags.is_on("new_pipeline_ui", attributes={"org_id": org_id}):
        ...

Falls back to env-var overrides (FEATURE_<FLAG>=true/false) and then
to hardcoded defaults when the GrowthBook SDK or API key is absent.
"""
from __future__ import annotations
import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ── Default flag values for the AetherOS platform ────────────────────────────

_DEFAULTS: Dict[str, bool] = {
    "new_pipeline_ui":           True,
    "bedrock_llm":               True,
    "council_strict_mode":       False,
    "marketplace_v2":            True,
    "chromadb_memory":           True,
    "langsmith_tracing":         False,
    "ab_test_run_button":        False,
    "scim_provisioning":         True,
    "saml_sso":                  True,
    "workloop_monitor":          True,
}


class _FeatureFlags:
    """Thin wrapper around GrowthBook SDK with env-var and default fallbacks."""

    def __init__(self) -> None:
        self._gb = None
        self._features: Dict[str, Any] = {}
        self._try_init_growthbook()

    def _try_init_growthbook(self) -> None:
        sdk_key = os.environ.get("GROWTHBOOK_SDK_KEY", "")
        api_host = os.environ.get("GROWTHBOOK_API_HOST", "https://cdn.growthbook.io")
        if not sdk_key:
            return
        try:
            from growthbook import GrowthBook
            self._gb = GrowthBook(
                api_host=api_host,
                client_key=sdk_key,
            )
            # Load features from GrowthBook CDN
            self._gb.load_features()
            logger.info("GrowthBook feature flags loaded (SDK key: %s...)", sdk_key[:8])
        except ImportError:
            logger.warning("growthbook package not available — using defaults")
        except Exception as exc:
            logger.warning("GrowthBook init failed (%s) — using defaults", exc)

    def is_on(
        self,
        flag: str,
        attributes: Optional[Dict[str, Any]] = None,
        default: bool = False,
    ) -> bool:
        # 1. Env-var override wins (FEATURE_NEW_PIPELINE_UI=true)
        env_key = f"FEATURE_{flag.upper()}"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            return env_val.lower() in ("1", "true", "yes")

        # 2. GrowthBook evaluation (respects targeting rules + A/B splits)
        if self._gb is not None:
            try:
                if attributes:
                    self._gb.set_attributes(attributes)
                result = self._gb.is_on(flag)
                if result is not None:
                    return bool(result)
            except Exception as exc:
                logger.debug("GrowthBook.is_on(%s) failed: %s", flag, exc)

        # 3. Platform defaults
        return _DEFAULTS.get(flag, default)

    def get_value(
        self,
        flag: str,
        fallback: Any = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Any:
        env_key = f"FEATURE_{flag.upper()}"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            try:
                return json.loads(env_val)
            except json.JSONDecodeError:
                return env_val

        if self._gb is not None:
            try:
                if attributes:
                    self._gb.set_attributes(attributes)
                val = self._gb.get_feature_value(flag, fallback)
                if val is not None:
                    return val
            except Exception as exc:
                logger.debug("GrowthBook.get_feature_value(%s) failed: %s", flag, exc)

        return _DEFAULTS.get(flag, fallback)

    def all_flags(self) -> Dict[str, bool]:
        result = dict(_DEFAULTS)
        for flag in _DEFAULTS:
            result[flag] = self.is_on(flag)
        return result


# Singleton
flags = _FeatureFlags()
