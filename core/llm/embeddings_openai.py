"""Embeddings from the install's OpenAI-compatible endpoint (KAN-219).

The embedder knew only Bedrock Titan and a local Ollama. The single-host production install has neither, so every
embedding was a zero vector ("All embedding providers failed ... Returning zero vector") and similarity search returned
noise. Setting EMBEDDING_OPENAI_MODEL (e.g. an NVIDIA retrieval model on the same endpoint as the chat model) makes the
endpoint the first embedding provider; unset, nothing changes. EMBEDDING_INPUT_TYPE is sent as `input_type` for
providers whose asymmetric models require it (NVIDIA: "passage" or "query").
"""
from __future__ import annotations

import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)


def configured() -> bool:
    return bool(os.environ.get("EMBEDDING_OPENAI_MODEL", "").strip())


async def embed(text: str) -> Optional[List[float]]:
    """The embedding vector, or None when not configured or the call failed (the caller falls back)."""
    model = os.environ.get("EMBEDDING_OPENAI_MODEL", "").strip()
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not model or not key:
        return None
    from aether_os.core.llm.openrouter_client import base_url   # lazy: keeps this module import-light
    payload = {"model": model, "input": [text[:8000]], "encoding_format": "float"}
    input_type = os.environ.get("EMBEDDING_INPUT_TYPE", "").strip()
    if input_type:
        payload["input_type"] = input_type
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as http:
            resp = await http.post(f"{base_url()}/embeddings", json=payload,
                                   headers={"Authorization": f"Bearer {key}"})
            resp.raise_for_status()
            vector = resp.json()["data"][0]["embedding"]
    except Exception as exc:
        logger.warning("OpenAI-compatible embedding (%s) failed: %s", model, exc)
        return None
    return vector if isinstance(vector, list) and vector else None
