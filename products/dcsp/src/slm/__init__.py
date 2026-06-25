"""
SLM + RAG wiring layer for DCSP.

LLM backend is selected at runtime via LLM_BACKEND env var.
  "fallback"    (default) — tries Bedrock → OpenRouter → Ollama in order
  "bedrock"     — Amazon Nova Pro via AWS Bedrock only
  "openrouter"  — OpenRouter API only (free tier available)
  "ollama"      — local Ollama only
"""

from __future__ import annotations

import os

from src.slm.context_builder import ContextBuilder
from src.slm.prompt_template import build_patch_prompt
from src.slm.fallback_client import FallbackLLMClient
from src.slm.openrouter_client import OpenRouterClient
from src.slm.bedrock_client import BedrockClient
from src.slm.ollama_client import OllamaClient

__all__ = [
    "FallbackLLMClient",
    "OpenRouterClient",
    "BedrockClient",
    "OllamaClient",
    "ContextBuilder",
    "build_patch_prompt",
]
