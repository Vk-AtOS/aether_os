"""
LLM Council — runs generated src/main.py through multiple LLM models for diverse code review.

Each model gives an independent perspective:
  - Claude:  Security & compliance focus
  - Gemini:  Architecture & scalability focus
  - Ollama:  Performance & simplicity focus

Results are aggregated into a CouncilReport with consensus issues and unique
findings per model.  Any model whose API key is absent is silently skipped —
the council runs with however many models are configured (minimum 1).

Usage:
    report = await run_council(source_code, run_id, project_name, domain)
    report_dict = asdict(report)
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class CouncilReview:
    """Single model's review of the generated codebase."""
    model: str                      # e.g. "claude", "gemini", "ollama"
    focus: str                      # e.g. "Security & compliance"
    issues: List[str] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)
    score: int = 0                  # 0-10
    raw_response: str = ""


@dataclass
class CouncilReport:
    """Aggregated multi-model code review."""
    run_id: str
    project_name: str
    domain: str
    reviews: List[CouncilReview] = field(default_factory=list)
    consensus_issues: List[str] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Prompt templates ──────────────────────────────────────────────────────────

_PROMPTS = {
    "claude": {
        "focus": "Security & compliance",
        "system": (
            "You are a senior security engineer performing a code review. "
            "Be specific — reference line numbers where possible. "
            "Format your response EXACTLY as:\n"
            "SCORE: <number 0-10>\n"
            "ISSUES:\n- <issue 1>\n- <issue 2>\n...\n"
            "STRENGTHS:\n- <strength 1>\n- <strength 2>\n..."
        ),
        "prompt_tmpl": (
            "Review this FastAPI application for security vulnerabilities and compliance gaps.\n"
            "Domain: {domain}\n\n"
            "Focus on: authentication flaws, SQL injection, hardcoded secrets, "
            "missing input validation, CORS misconfiguration, privilege escalation risks, "
            "and GDPR/HIPAA data handling issues.\n\n"
            "Code:\n```python\n{code}\n```"
        ),
    },
    "gemini": {
        "focus": "Architecture & scalability",
        "system": (
            "You are a senior software architect performing a code review. "
            "Focus on long-term maintainability and scalability. "
            "Format your response EXACTLY as:\n"
            "SCORE: <number 0-10>\n"
            "ISSUES:\n- <issue 1>\n- <issue 2>\n...\n"
            "STRENGTHS:\n- <strength 1>\n- <strength 2>\n..."
        ),
        "prompt_tmpl": (
            "Review this FastAPI application for architecture problems and scalability issues.\n"
            "Domain: {domain}\n\n"
            "Focus on: database design, API structure, separation of concerns, "
            "error handling patterns, async usage, connection pool management, "
            "and code maintainability.\n\n"
            "Code:\n```python\n{code}\n```"
        ),
    },
    "ollama": {
        "focus": "Performance & simplicity",
        "system": (
            "You are a pragmatic engineer doing a performance and code quality review. "
            "Look for unnecessary complexity and optimization opportunities. "
            "Format your response EXACTLY as:\n"
            "SCORE: <number 0-10>\n"
            "ISSUES:\n- <issue 1>\n- <issue 2>\n...\n"
            "STRENGTHS:\n- <strength 1>\n- <strength 2>\n..."
        ),
        "prompt_tmpl": (
            "Review this FastAPI application for performance anti-patterns "
            "and unnecessary complexity.\n"
            "Domain: {domain}\n\n"
            "Focus on: N+1 queries, missing indexes, blocking I/O, "
            "over-engineering, dead code, and simplification opportunities.\n\n"
            "Code:\n```python\n{code}\n```"
        ),
    },
}

_MAX_CODE_CHARS = 40_000  # trim very large files to keep tokens reasonable


# ── Parser ────────────────────────────────────────────────────────────────────

def _parse_review_response(raw: str, model: str, focus: str) -> CouncilReview:
    """
    Parse the structured LLM response into a CouncilReview.

    Expected format:
        SCORE: 7
        ISSUES:
        - Issue one
        - Issue two
        STRENGTHS:
        - Strength one
    """
    raw_stripped = raw.strip()

    # Extract score
    score = 5  # default if not parseable
    score_match = re.search(r"SCORE\s*:\s*(\d+)", raw_stripped, re.IGNORECASE)
    if score_match:
        score = min(10, max(0, int(score_match.group(1))))

    def _extract_list(section_name: str) -> List[str]:
        """Extract bullet list items after a section header."""
        # Match everything between this section and the next, or end of string
        pattern = rf"{section_name}\s*:?\s*\n(.*?)(?=\n[A-Z]{{3,}}:|\Z)"
        match = re.search(pattern, raw_stripped, re.IGNORECASE | re.DOTALL)
        if not match:
            return []
        block = match.group(1)
        items = []
        for line in block.splitlines():
            line = line.strip()
            # Accept lines starting with -, *, •, numbers, or just non-empty
            if line.startswith(("-", "*", "•")):
                items.append(line.lstrip("-*• ").strip())
            elif re.match(r"^\d+[.)]\s+", line):
                items.append(re.sub(r"^\d+[.)]\s+", "", line).strip())
            elif line and not re.match(r"^[A-Z]{3,}:", line):
                items.append(line)
        return [i for i in items if i]

    issues = _extract_list("ISSUES")
    strengths = _extract_list("STRENGTHS")

    # Fallback: if structured parse fails, try to extract any bullet lines
    if not issues and not strengths:
        bullets = [
            line.lstrip("-*• ").strip()
            for line in raw_stripped.splitlines()
            if line.strip().startswith(("-", "*", "•")) and line.strip()[2:].strip()
        ]
        issues = bullets[:5]

    return CouncilReview(
        model=model,
        focus=focus,
        issues=issues,
        strengths=strengths,
        score=score,
        raw_response=raw_stripped[:2000],  # cap stored raw response
    )


# ── Per-model callers ─────────────────────────────────────────────────────────

async def _call_via_bedrock(code: str, domain: str, role_key: str) -> Optional[CouncilReview]:
    """Call Claude on Amazon Bedrock (used when direct Anthropic API key is absent)."""
    aws_key = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
    aws_secret = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
    if not aws_key or not aws_secret:
        return None
    try:
        import boto3, json as _json  # type: ignore
        spec = _PROMPTS[role_key]
        model_id = (
            os.environ.get("BEDROCK_MODEL_HEAVY", "us.anthropic.claude-sonnet-4-6")
            if role_key == "claude"
            else os.environ.get("BEDROCK_MODEL_LIGHT", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
        )
        region = os.environ.get("AWS_REGION", "us-east-1")
        body = _json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "system": spec["system"],
            "messages": [{
                "role": "user",
                "content": spec["prompt_tmpl"].format(domain=domain, code=code[:_MAX_CODE_CHARS]),
            }],
        })
        def _invoke():
            c = boto3.client(
                "bedrock-runtime", region_name=region,
                aws_access_key_id=aws_key, aws_secret_access_key=aws_secret,
            )
            resp = c.invoke_model(modelId=model_id, body=body,
                                  contentType="application/json", accept="application/json")
            return _json.loads(resp["body"].read()).get("content", [{}])[0].get("text", "")

        raw = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, _invoke), timeout=90
        )
        logger.info("CouncilReviewer: Bedrock/%s review complete (len=%d)", role_key, len(raw))
        return _parse_review_response(raw, f"claude-bedrock ({model_id.split('.')[-1]})", spec["focus"])
    except Exception as exc:
        logger.warning("CouncilReviewer: Bedrock/%s failed — %s", role_key, exc)
        return None


async def _call_claude(code: str, domain: str) -> Optional[CouncilReview]:
    """Call Anthropic Claude for a security-focused review. Falls back to Bedrock."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        try:
            import anthropic  # type: ignore
            spec = _PROMPTS["claude"]
            client = anthropic.AsyncAnthropic(api_key=api_key)
            msg = await asyncio.wait_for(
                client.messages.create(
                    model=os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5"),
                    max_tokens=1024,
                    system=spec["system"],
                    messages=[{
                        "role": "user",
                        "content": spec["prompt_tmpl"].format(
                            domain=domain, code=code[:_MAX_CODE_CHARS],
                        ),
                    }],
                ),
                timeout=60,
            )
            raw = msg.content[0].text if msg.content else ""
            logger.info("CouncilReviewer: Claude review complete (len=%d)", len(raw))
            return _parse_review_response(raw, "claude", spec["focus"])
        except Exception as exc:
            logger.warning("CouncilReviewer: Claude API failed — %s", exc)

    # Fallback: use Bedrock (Sonnet) when direct API key is absent or failed
    return await _call_via_bedrock(code, domain, "claude")


async def _call_gemini(code: str, domain: str) -> Optional[CouncilReview]:
    """Call Google Gemini for an architecture-focused review. Falls back to Bedrock Haiku."""
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if api_key and api_key not in ("REPLACE_WITH_YOUR_GEMINI_KEY", "your_google_api_key"):
        try:
            from google import genai  # type: ignore
            spec = _PROMPTS["gemini"]
            client = genai.Client(api_key=api_key)
            full_prompt = f"{spec['system']}\n\n{spec['prompt_tmpl'].format(domain=domain, code=code[:_MAX_CODE_CHARS])}"
            response = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: client.models.generate_content(model="gemini-2.0-flash", contents=full_prompt),
                ),
                timeout=60,
            )
            raw = response.text or ""
            logger.info("CouncilReviewer: Gemini review complete (len=%d)", len(raw))
            return _parse_review_response(raw, "gemini", spec["focus"])
        except Exception as exc:
            logger.warning("CouncilReviewer: Gemini call failed — %s", exc)

    # Fallback: Bedrock Haiku for architecture review
    return await _call_via_bedrock(code, domain, "gemini")


async def _call_ollama(code: str, domain: str) -> Optional[CouncilReview]:
    """Call local Ollama for a performance-focused review."""
    ollama_base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    ollama_model = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
    try:
        import httpx
        spec = _PROMPTS["ollama"]
        payload = {
            "model": ollama_model,
            "prompt": spec["prompt_tmpl"].format(
                domain=domain,
                code=code[:_MAX_CODE_CHARS],
            ),
            "system": spec["system"],
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(f"{ollama_base}/api/generate", json=payload)
            r.raise_for_status()
            raw = r.json().get("response", "")
        logger.info("CouncilReviewer: Ollama review complete (len=%d)", len(raw))
        return _parse_review_response(raw, "ollama", spec["focus"])
    except Exception as exc:
        logger.warning("CouncilReviewer: Ollama call failed — %s", exc)
        return None


# ── Consensus ─────────────────────────────────────────────────────────────────

def _find_consensus(reviews: List[CouncilReview], min_models: int = 2) -> List[str]:
    """
    Find issues mentioned by at least min_models models.

    Uses a simple keyword overlap heuristic: two issues are considered the same
    if they share 3+ significant words (ignoring stop words and short words).
    """
    _STOP = frozenset({
        "the", "a", "an", "in", "of", "for", "to", "and", "or", "is", "are",
        "it", "its", "this", "that", "be", "by", "on", "at", "with", "from",
        "not", "no", "use", "used", "using", "when", "where", "which", "has",
        "have", "does", "do", "can", "all", "any", "should", "would", "will",
    })

    def _words(text: str) -> frozenset:
        tokens = re.findall(r"[a-z]{4,}", text.lower())
        return frozenset(t for t in tokens if t not in _STOP)

    # Gather all (issue_text, model_name) pairs
    all_issues: List[tuple] = []
    for review in reviews:
        for issue in review.issues:
            all_issues.append((issue, review.model))

    if len(all_issues) < min_models:
        return []

    # Cluster by word overlap
    used: set = set()
    consensus: List[str] = []

    for i, (issue_a, model_a) in enumerate(all_issues):
        if i in used:
            continue
        words_a = _words(issue_a)
        if len(words_a) < 2:
            continue
        cluster_models = {model_a}
        for j, (issue_b, model_b) in enumerate(all_issues):
            if j == i or j in used or model_b == model_a:
                continue
            words_b = _words(issue_b)
            overlap = len(words_a & words_b)
            if overlap >= 2:
                cluster_models.add(model_b)
                used.add(j)

        if len(cluster_models) >= min_models:
            consensus.append(issue_a)
            used.add(i)

    return consensus


# ── Main entry point ──────────────────────────────────────────────────────────

async def run_council(
    source_code: str,
    run_id: str,
    project_name: str = "",
    domain: str = "general",
) -> CouncilReport:
    """
    Run the LLM Council: up to 3 parallel model reviews of generated source_code.

    Gracefully skips any model whose API key is absent or whose service is unreachable.
    Returns a CouncilReport with per-model reviews and consensus issues.
    """
    logger.info(
        "CouncilReviewer: starting council review for run_id=%s project=%s domain=%s",
        run_id, project_name, domain,
    )

    # Run all three reviewers in parallel; each returns None on skip/failure
    claude_task = asyncio.create_task(_call_claude(source_code, domain))
    gemini_task = asyncio.create_task(_call_gemini(source_code, domain))
    ollama_task = asyncio.create_task(_call_ollama(source_code, domain))

    results = await asyncio.gather(claude_task, gemini_task, ollama_task, return_exceptions=True)

    reviews: List[CouncilReview] = []
    for result in results:
        if isinstance(result, CouncilReview):
            reviews.append(result)
        elif isinstance(result, Exception):
            logger.warning("CouncilReviewer: reviewer raised exception — %s", result)

    if not reviews:
        logger.warning(
            "CouncilReviewer: no models completed a review for run_id=%s. "
            "Check ANTHROPIC_API_KEY / GOOGLE_API_KEY / Ollama availability.",
            run_id,
        )

    consensus = _find_consensus(reviews, min_models=2)

    logger.info(
        "CouncilReviewer: complete — %d reviews, %d consensus issues",
        len(reviews), len(consensus),
    )

    return CouncilReport(
        run_id=run_id,
        project_name=project_name or run_id,
        domain=domain,
        reviews=reviews,
        consensus_issues=consensus,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
