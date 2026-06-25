"""
Prompt templates for SLM repair.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.dfle.log_parser import ParsedLog as ParsedFailure


def build_patch_prompt(context: str, failure: ParsedFailure) -> str:
    """
    Construct a prompt for DeepSeek Coder to generate a repair patch.

    Args:
        context: The RAG context containing relevant code snippets.
        failure: The parsed failure information.

    Returns:
        A formatted prompt string.
    """
    trace_text = failure.primary_trace.raw_text if failure.primary_trace else "No traceback available."

    prompt = f"""
You are an expert software engineer and automated repair tool.
Given the following CI failure traceback and code context, generate a repair patch.

REQUIREMENTS:
1. Output ONLY a unified diff patch.
2. No explanation, no markdown blocks, no leading/trailing text. Just the diff.
3. The patch must apply to a single file.
4. Max 40 lines changed.
5. Fix the root cause identified in the traceback.

FAILURE TRACEBACK:
{trace_text}

CODE CONTEXT:
{context}

UNIFIED DIFF:
"""
    return prompt.strip()
