"""
AetherOS — Context Compressor

Reduces input token count before expensive LLM calls by compressing
accumulated pipeline context using Claude Haiku (cheap fast model).

Cost math:
  - Uncompressed context across 12 phases: ~20,000 tokens at $0.003/1K = $0.06
  - Haiku compression call: ~2,000 input + 800 output = 2,800 tokens at $0.00025/1K = $0.0007
  - Compressed context: ~3,000 tokens at $0.003/1K = $0.009
  - Net saving per heavy call: $0.06 - $0.009 - $0.0007 ≈ $0.05 per call
  - 12 phases × $0.05 = $0.60 saved per run

Compression is only applied when:
  1. Input exceeds COMPRESS_THRESHOLD tokens (default: 6,000)
  2. Task type is "heavy" (code generation, security, etc.)
  3. Haiku is available (ANTHROPIC_API_KEY set)
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Token count threshold above which compression is triggered
COMPRESS_THRESHOLD = 6_000       # ~6K tokens ≈ 4,500 words
COMPRESSION_RATIO_TARGET = 0.30  # compress to 30% of original size


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: 1 token ≈ 4 chars (English)."""
    return len(text) // 4


def _compression_system_prompt() -> str:
    return (
        "You are a context compression expert. "
        "Your task is to compress the provided technical context into a dense summary. "
        "Rules:\n"
        "1. Preserve ALL technical decisions, file paths, API contracts, and data models.\n"
        "2. Remove verbose explanations, boilerplate, and repeated information.\n"
        "3. Output structured JSON-like bullet points, not prose.\n"
        "4. Target 25-35% of the original token count.\n"
        "5. Never omit: architecture decisions, security findings, test results, URLs, IDs.\n"
        "Output ONLY the compressed context. No preamble."
    )


async def compress_context(
    context: str,
    task_type: str = "code_generation",
    force: bool = False,
) -> tuple[str, bool]:
    """
    Compress context if it exceeds the threshold.

    Returns (compressed_context, was_compressed).
    If compression fails or is not needed, returns (original_context, False).
    """
    estimated_tokens = _estimate_tokens(context)

    if not force and estimated_tokens < COMPRESS_THRESHOLD:
        return context, False

    # Only compress for heavy tasks where savings are significant
    heavy_tasks = {"code_generation", "security_scan", "testing", "architecture", "review"}
    if not force and task_type not in heavy_tasks:
        return context, False

    # Need Anthropic API key for Haiku compression
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return context, False

    try:
        import anthropic  # type: ignore
        client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=max(1024, int(estimated_tokens * COMPRESSION_RATIO_TARGET * 4 // 4)),
            system=_compression_system_prompt(),
            messages=[{
                "role": "user",
                "content": f"Compress this pipeline context:\n\n{context}"
            }],
        )

        compressed = response.content[0].text if response.content else context
        compressed_tokens = _estimate_tokens(compressed)
        ratio = compressed_tokens / max(estimated_tokens, 1)

        logger.info(
            "Context compressed: %d → %d tokens (%.0f%% reduction, task=%s)",
            estimated_tokens, compressed_tokens, (1 - ratio) * 100, task_type,
        )
        return compressed, True

    except Exception as exc:
        logger.debug("Context compression failed (using original): %s", exc)
        return context, False


class ContextCompressor:
    """
    Stateful compressor that tracks savings across a pipeline run.
    """

    def __init__(self) -> None:
        self.tokens_saved: int = 0
        self.compressions: int = 0

    async def maybe_compress(
        self,
        prompt: str,
        task_type: str = "code_generation",
    ) -> str:
        """
        Compress the prompt if beneficial. Returns the (possibly compressed) prompt.
        Updates internal savings stats.
        """
        before = _estimate_tokens(prompt)
        compressed, did_compress = await compress_context(prompt, task_type=task_type)
        if did_compress:
            after = _estimate_tokens(compressed)
            self.tokens_saved += max(0, before - after)
            self.compressions += 1
        return compressed
