"""
Google Gemini client for DCSP patch generation.
Set LLM_BACKEND=gemini and GEMINI_API_KEY to use this.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gemini-2.0-flash"


class GeminiClient:
    """LLM client using the Google Generative Language API."""

    def __init__(self) -> None:
        self.api_key = os.environ.get("GEMINI_API_KEY", "")
        self.model = os.environ.get("GEMINI_MODEL", _DEFAULT_MODEL)
        self.timeout = 60

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _call(self, system: str, user: str, model: str) -> Optional[str]:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={self.api_key}"
        )
        payload = json.dumps({
            "contents": [
                {"role": "user", "parts": [{"text": f"{system}\n\n{user}"}]}
            ],
            "generationConfig": {"maxOutputTokens": 2048, "temperature": 0.1},
        }).encode()

        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            logger.warning("Gemini API call failed: %s", e)
            return None

    def generate_patch(self, system_prompt: str, user_prompt: str, max_retries: int = 2) -> Optional[str]:
        for _ in range(max_retries):
            result = self._call(system_prompt, user_prompt, self.model)
            if result and ("---" in result or "@@" in result):
                return result
        return None
