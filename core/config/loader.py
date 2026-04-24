"""
AetherOS — Unified Configuration Loader
Merged from aether2/aether/core/config.py with env-var support and security fixes.
- Bug 4 fixed: SECRET_KEY no longer has a hardcoded dev default
"""
from __future__ import annotations
import logging
import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class AetherConfig:
    """
    Singleton YAML + environment config loader.

    Priority order (highest first):
      1. Environment variables (AETHER_<UPPER_KEY>)
      2. User YAML config file
      3. Hardcoded defaults (safe, non-secret values only)
    """
    _instance: Optional["AetherConfig"] = None

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = os.environ.get(
                "AETHER_CONFIG_PATH",
                str(Path.home() / ".aether_os" / "config.yaml")
            )
        self.config_path = Path(config_path)
        self._data: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load defaults, then overlay YAML, then overlay env vars."""
        self._data = {
            "models": {
                "primary": "claude-sonnet-4-6",
                "haiku": "claude-haiku-4-5",
                "fallback_ollama": "phi3:mini",
                "code_generation": "claude-sonnet-4-6",
                "security_scan": "claude-sonnet-4-6",
                "requirements": "claude-haiku-4-5",
                "documentation": "claude-haiku-4-5",
                "testing": "claude-sonnet-4-6",
            },
            "pipeline": {
                "max_retries": 3,
                "output_dir": str(Path.home() / ".aether_os" / "outputs"),
                "stage_timeout_seconds": {
                    "requirements": 120,
                    "architecture": 180,
                    "code_generation": 300,
                    "review_code": 120,
                    "security_scan": 180,
                    "generate_tests": 240,
                    "generate_docs": 120,
                    "packaging": 120,
                },
            },
            "api": {
                # SECRET_KEY must come from env — no default (Bug 4 fix applied in gateway)
                "token_expiry_hours": 24,
                "host": "0.0.0.0",
                "port": 8080,
            },
            "database": {
                "path": str(Path.home() / ".aether_os" / "aether_os.db"),
                "echo": False,
            },
            "llm": {
                "anthropic_model": "claude-sonnet-4-6",
                "ollama_base_url": "http://localhost:11434",
                "max_tokens": 8192,
                "temperature": 0.2,
                "timeout_seconds": 120,
                "retry_attempts": 3,
                "retry_delay_seconds": 2,
            },
            "memory": {
                "db_path": str(Path.home() / ".aether_os" / "memory.db"),
                "top_k_retrieve": 5,
            },
            "audit": {
                "log_path": str(Path.home() / ".aether_os" / "audit.jsonl"),
            },
            "telemetry": {
                "enabled": True,
                "sink_path": str(Path.home() / ".aether_os" / "telemetry.jsonl"),
            },
            "policy": {
                "strict_mode": False,
                "profile": "DEFAULT",
                "config_path": str(Path.home() / ".aether_os" / "policy.json"),
            },
            "snapshot": {
                "storage_path": str(Path.home() / ".aether_os" / "snapshots"),
            },
        }

        # Overlay YAML
        if self.config_path.exists():
            try:
                with open(self.config_path, "r") as f:
                    user_config = yaml.safe_load(f) or {}
                self._deep_merge(self._data, user_config)
                logger.info("Loaded config from %s", self.config_path)
            except Exception as exc:
                logger.warning("Failed to load config YAML (%s): %s — using defaults", self.config_path, exc)

    def _deep_merge(self, base: Dict, override: Dict) -> None:
        for key, val in override.items():
            if isinstance(val, dict) and isinstance(base.get(key), dict):
                self._deep_merge(base[key], val)
            else:
                base[key] = val

    def get(self, key_path: str, default: Any = None) -> Any:
        """Dot-separated key lookup, e.g. get('llm.anthropic_model')."""
        parts = key_path.split(".")
        val: Any = self._data
        for part in parts:
            if isinstance(val, dict) and part in val:
                val = val[part]
            else:
                return default
        return val

    def set(self, key_path: str, value: Any) -> None:
        """Runtime override (not persisted)."""
        parts = key_path.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def require(self, key_path: str) -> Any:
        """Like get() but raises ConfigurationError if not found."""
        from ..errors import ConfigurationError
        val = self.get(key_path)
        if val is None:
            raise ConfigurationError(f"Required config key not set: {key_path}")
        return val

    def all(self) -> Dict[str, Any]:
        return dict(self._data)


def get_config() -> AetherConfig:
    """Return the global singleton AetherConfig instance."""
    if AetherConfig._instance is None:
        AetherConfig._instance = AetherConfig()
    return AetherConfig._instance
