"""
Client for interacting with local Ollama service.
"""

from __future__ import annotations

import os
import requests
import json
import threading
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class OllamaClient:
    """Client for generating patches using Ollama and DeepSeek Coder."""

    _semaphore = threading.Semaphore(3)

    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        self.base_url = (base_url or 
                         os.environ.get("OLLAMA_URL") or 
                         os.environ.get("OLLAMA_HOST") or 
                         "http://localhost:11434")
        self.model = model or os.environ.get("OLLAMA_MODEL", "deepseek-coder:6.7b")
        self.generate_url = f"{self.base_url}/api/generate"
        self.tags_url = f"{self.base_url}/api/tags"
        self.timeout = 60

    def is_available(self) -> bool:
        """Check if Ollama service is reachable."""
        try:
            resp = requests.get(self.tags_url, timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    def generate(self, system: str, user: str) -> Optional[str]:
        """Raw generate call with connection pooling."""
        if not self.is_available():
            logger.warning("Ollama unreachable, skipping generation.")
            return None

        prompt = f"{system}\n\nUser: {user}\n\nAssistant:"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False
        }

        with self._semaphore:
            try:
                response = requests.post(
                    self.generate_url,
                    json=payload,
                    timeout=self.timeout
                )
                response.raise_for_status()
                data = response.json()
                return data.get("response")
            except Exception as e:
                logger.error(f"Ollama generation failed: {e}")
                return None

    def validate_diff(self, text: str) -> bool:
        """Returns True if text contains valid diff markers."""
        if not text:
            return False
        required = ["---", "+++", "@@"]
        return all(marker in text for marker in required)

    def generate_patch(self, system: str, user: str, max_retries: int = 3) -> Optional[str]:
        """
        Generate a repair patch with validation and retries.
        """
        current_user_prompt = user
        
        for attempt in range(max_retries):
            response = self.generate(system, current_user_prompt)
            if response and self.validate_diff(response):
                return response
            
            # If invalid, update prompt for retry
            current_user_prompt = (f"{user}\n\nNote: Previous response was not a valid "
                                   f"unified diff. Ensure you start with --- a/filename "
                                   f"and include +++, @@ markers. Try again.")
            
        return None
