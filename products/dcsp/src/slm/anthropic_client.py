"""
Anthropic Claude client for DCSP patch generation.
Set LLM_BACKEND=anthropic and ANTHROPIC_API_KEY to use this.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_FALLBACK_MODELS = ["claude-haiku-4-5-20251001", "claude-sonnet-4-6"]


class AnthropicClient:
    """LLM client using the Anthropic Messages API directly (no SDK required)."""

    def __init__(self) -> None:
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = os.environ.get("ANTHROPIC_MODEL", _DEFAULT_MODEL)
        self.base_url = "https://api.anthropic.com/v1/messages"
        self.timeout = 90

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _call(self, system: str, user: str, model: str) -> Optional[str]:
        payload = json.dumps({
            "model": model,
            "max_tokens": 2048,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }).encode()

        req = urllib.request.Request(
            self.base_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
            return data["content"][0]["text"]
        except urllib.error.HTTPError as e:
            body = e.read(500).decode(errors="replace")
            logger.warning("Anthropic API HTTP %s: %s", e.code, body)
            return None
        except Exception as e:
            logger.warning("Anthropic API call failed: %s", e)
            return None

    def generate_patch(self, system_prompt: str, user_prompt: str, max_retries: int = 3) -> Optional[str]:
        models_to_try = [self.model] + [m for m in _FALLBACK_MODELS if m != self.model]
        for model in models_to_try[:max_retries]:
            logger.info("AnthropicClient: trying model %s", model)
            result = self._call(system_prompt, user_prompt, model)
            if result and ("---" in result or "@@" in result):
                logger.info("AnthropicClient: patch generated via %s", model)
                return result
            if result:
                logger.warning("AnthropicClient: %s returned text but no diff markers", model)
        logger.warning("AnthropicClient: all models exhausted")
        return None
