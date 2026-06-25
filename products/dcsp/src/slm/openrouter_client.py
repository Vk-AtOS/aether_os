"""
OpenRouter client — free/cheap fallback LLM provider.
Supports mistral-7b-instruct, llama-3-8b, codestral, etc.
No AWS account needed; free tier available at openrouter.ai.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_MODELS = [
    "mistralai/mistral-7b-instruct:free",
    "meta-llama/llama-3-8b-instruct:free",
    "microsoft/phi-3-mini-128k-instruct:free",
]


class OpenRouterClient:
    """LLM client using OpenRouter API (openrouter.ai)."""

    def __init__(self) -> None:
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self.model = os.environ.get("OPENROUTER_MODEL", _DEFAULT_MODELS[0])
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        self.timeout = 60

    def is_available(self) -> bool:
        return bool(self.api_key)

    def validate_response(self, text: str) -> bool:
        if not text:
            return False
        return "---" in text or "@@" in text

    def _call(self, system: str, user: str, model: str) -> Optional[str]:
        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": 2048,
            "temperature": 0.1,
        }).encode()

        req = urllib.request.Request(
            self.base_url,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/Vk-AtOS/DCSP",
                "X-Title": "DCSP AutoFix",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
                return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:200]
            logger.warning("OpenRouter HTTP %s for model %s: %s", e.code, model, body)
            return None
        except Exception as e:
            logger.warning("OpenRouter call failed for model %s: %s", model, e)
            return None

    def generate_patch(self, system_prompt: str, user_prompt: str, max_retries: int = 2) -> Optional[str]:
        if not self.is_available():
            logger.info("OpenRouter: no API key, skipping")
            return None

        # Try primary model first, then free-tier fallbacks
        models_to_try = [self.model] + [m for m in _DEFAULT_MODELS if m != self.model]

        for model in models_to_try:
            for attempt in range(max_retries):
                extra = "" if attempt == 0 else (
                    "\n\nIMPORTANT: Return ONLY a valid unified diff starting with "
                    "'--- a/filename' and including +++ and @@ markers."
                )
                text = self._call(system_prompt, user_prompt + extra, model)
                if text and self.validate_response(text):
                    logger.info("OpenRouter patch generated via %s", model)
                    return text
                if text:
                    logger.warning("OpenRouter model %s attempt %d: invalid diff format", model, attempt + 1)

        return None
