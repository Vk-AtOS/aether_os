"""
SLM wiring layer for the AetherOS CI/CD phase.
OllamaClient is replaced by the unified LLM client (Anthropic primary + Ollama fallback).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from aether_os.core.llm.client import get_llm_client
from aether_os.phases.p08_cicd.slm.context_builder import ContextBuilder
from aether_os.phases.p08_cicd.slm.prompts import PromptTemplates

logger = logging.getLogger(__name__)


class OllamaClient:
    """
    Shim that routes through the unified LLM client (Anthropic primary + Ollama fallback).
    Drop-in replacement for the original OllamaClient interface.
    """

    def __init__(self) -> None:
        self._llm = get_llm_client()

    def generate_patch(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Synchronous wrapper — runs async LLM call in an event loop."""
        combined = f"{system_prompt}\n\n{user_prompt}"
        try:
            try:
                asyncio.get_running_loop()
                # Inside async context: run in thread pool
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        asyncio.run,
                        self._llm.call(combined, task_type="code_generation"),
                    )
                    return future.result(timeout=120)
            except RuntimeError:
                # No running loop
                return asyncio.run(
                    self._llm.call(combined, task_type="code_generation")
                )
        except Exception as exc:
            logger.error("OllamaClient shim: LLM call failed: %s", exc)
            return None


__all__ = ["OllamaClient", "ContextBuilder", "PromptTemplates"]
