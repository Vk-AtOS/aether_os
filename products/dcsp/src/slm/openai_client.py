"""
OpenAI client for DCSP patch generation.
Set LLM_BACKEND=openai and OPENAI_API_KEY to use this.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIClient:
    """LLM client using the OpenAI Chat Completions API."""

    def __init__(self) -> None:
        self.api_key = os.environ.get("OPENAI_API_KEY", "")
        self.model = os.environ.get("OPENAI_MODEL", _DEFAULT_MODEL)
        self.base_url = "https://api.openai.com/v1/chat/completions"
        self.timeout = 60

    def is_available(self) -> bool:
        return bool(self.api_key)

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
            self.base_url, data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.warning("OpenAI API call failed: %s", e)
            return None

    def generate_patch(self, system_prompt: str, user_prompt: str, max_retries: int = 2) -> Optional[str]:
        for _ in range(max_retries):
            result = self._call(system_prompt, user_prompt, self.model)
            if result and ("---" in result or "@@" in result):
                return result
        return None
