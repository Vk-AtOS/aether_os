"""
AetherOS — LLM Council

Two review gates:
  PreFlightCouncil  — validates a factory request before the pipeline starts
  DeliveryCouncil   — validates pipeline output before delivery to the client

Result schema (both councils):
  {
    "passed":      bool,
    "score":       float,   # 0.0 – 1.0
    "reason":      str,
    "suggestions": list[str],
  }

Behaviour is controlled by two env vars:
  COUNCIL_ENABLED=true      — run council checks (default: true)
  COUNCIL_STRICT_MODE=false — when true, failed checks block the operation
                              (default: false — log warning but always proceed)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_COUNCIL_SYSTEM = (
    "You are a senior software engineering council member reviewing requests for an "
    "autonomous code-generation system. Be concise, structured, and objective."
)

_PREFLIGHT_PROMPT_TMPL = """\
Review the following software factory request and evaluate it.

Request: {raw_input}
Domain: {domain}

Evaluate on these criteria:
1. Clarity — is the requirement specific enough to build from?
2. Feasibility — is it technically achievable by an automated system?
3. Safety — does it request anything harmful, unethical, or illegal?
4. Scope — is the scope reasonable for a single automated pipeline run?

Return ONLY valid JSON (no markdown, no fences):
{{
  "passed": true|false,
  "score": 0.0-1.0,
  "reason": "one sentence summary",
  "suggestions": ["improvement if any", "..."]
}}

Pass if score >= 0.6 and no safety violations.
"""

_DELIVERY_PROMPT_TMPL = """\
Review the following automated pipeline delivery summary.

Project: {project_name}
Domain: {domain}
Phases completed: {phases_completed}
Phase results summary: {phases_summary}

Evaluate on these criteria:
1. Completeness — did all required phases complete successfully?
2. Quality — are there any obvious failures or critical errors?
3. Consistency — do phase results indicate a coherent deliverable?
4. Security — were security and review phases passed?

Return ONLY valid JSON (no markdown, no fences):
{{
  "passed": true|false,
  "score": 0.0-1.0,
  "reason": "one sentence summary",
  "suggestions": ["follow-up action if any", "..."]
}}

Pass if score >= 0.5 and no critical phase failures.
"""

_PASS_RESULT: Dict[str, Any] = {
    "passed": True,
    "score": 1.0,
    "reason": "Council skipped (COUNCIL_ENABLED=false)",
    "suggestions": [],
}

_ERROR_RESULT: Dict[str, Any] = {
    "passed": False,
    "score": 0.0,
    "reason": "Council evaluation failed (LLM error) — manual review recommended",
    "suggestions": ["Review pipeline output manually before delivery"],
}


def _is_enabled() -> bool:
    return os.environ.get("COUNCIL_ENABLED", "true").lower() != "false"


def _is_strict() -> bool:
    # Default to strict in production, permissive in dev/staging
    _env = os.environ.get("ENVIRONMENT", "development").lower()
    _default = "true" if _env == "production" else "false"
    return os.environ.get("COUNCIL_STRICT_MODE", _default).lower() == "true"


def _parse_council_response(raw: str) -> Dict[str, Any]:
    """Extract the JSON council result from an LLM response."""
    import re
    raw = raw.strip()

    # Try direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Extract JSON object from prose
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    logger.warning("Council: could not parse LLM response as JSON: %s", raw[:200])
    return _ERROR_RESULT.copy()


class PreFlightCouncil:
    """Validates a factory request before the pipeline starts."""

    async def run(
        self,
        raw_input: str,
        domain: str = "general",
        org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not _is_enabled():
            return _PASS_RESULT.copy()

        from aether_os.core.llm.client import get_llm_client
        client = get_llm_client()

        prompt = _PREFLIGHT_PROMPT_TMPL.format(
            raw_input=raw_input[:2000],
            domain=domain,
        )
        try:
            raw = await client.call(
                prompt,
                task_type="classify",
                system=_COUNCIL_SYSTEM,
                max_tokens=512,
                org_id=org_id,
            )
            result = _parse_council_response(raw)
            logger.info(
                "PreFlightCouncil: passed=%s score=%.2f reason=%s",
                result.get("passed"),
                result.get("score", 0.0),
                result.get("reason", ""),
            )
            return result
        except Exception as exc:
            logger.warning("PreFlightCouncil: LLM call failed — %s", exc)
            return _ERROR_RESULT.copy()


class BackendAuditCouncil:
    """
    Post-generation focused code audit for p04 backend output.

    Runs 4 narrow, verdictable checks against the generated main.py.
    Each check is sent to a *different* model so the council is genuinely
    multi-model, not just one model called four times.

    Token budget: ~8 KB of code + ~50 token prompt + 150 token reply per check.
    Total: ~4 API calls, each ~8K tokens in, ~150 out.

    Returns:
      {
        "passed":      bool,
        "failures":    [{"check": str, "label": str, "detail": str, "model": str}],
        "corrections": str,   # newline-joined correction instructions for retry
      }
    """

    _CHECKS = [
        {
            "id": "auth_enforcement",
            "label": "JWT auth on mutation routes",
            "prompt_tmpl": (
                "FastAPI code below. Do ALL POST, PUT, and DELETE routes use a JWT "
                "auth dependency (Depends(verify_token), Depends(get_current_user), "
                "or equivalent)?\n"
                "Reply with exactly: PASS  or  FAIL\n"
                "If FAIL, add a second line: MISSING: <route paths separated by commas>\n\n"
                "Code:\n{code}"
            ),
            "correction": (
                "CORRECTION: Every POST, PUT, and DELETE route MUST include "
                "a JWT auth dependency. Add `user=Depends(verify_token)` (or equivalent) "
                "to each mutation route that is currently missing it."
            ),
        },
        {
            "id": "schema_consistency",
            "label": "Pydantic model / SQL column parity",
            "prompt_tmpl": (
                "Python code below. Does every field in every Pydantic BaseModel "
                "have a matching column in the corresponding CREATE TABLE SQL statement?\n"
                "Reply with exactly: PASS  or  FAIL\n"
                "If FAIL, add a second line: MISMATCH: <ModelName.field_name has no SQL column>\n\n"
                "Code:\n{code}"
            ),
            "correction": (
                "CORRECTION: Every Pydantic model field must have a matching column in "
                "its CREATE TABLE SQL. Add the missing columns to the SQL, "
                "or remove the extra fields from the model."
            ),
        },
        {
            "id": "org_isolation",
            "label": "Tenant org_id row filtering",
            "prompt_tmpl": (
                "FastAPI multi-tenant code below. Do ALL list (GET) and detail (GET /{id}) "
                "endpoints filter their SQL queries with a WHERE org_id=? clause?\n"
                "Reply with exactly: PASS  or  FAIL\n"
                "If FAIL, add a second line: UNFILTERED: <endpoint paths>\n\n"
                "Code:\n{code}"
            ),
            "correction": (
                "CORRECTION: Every SELECT query in list and detail endpoints must include "
                "WHERE org_id=? filtered by the authenticated user's org_id. "
                "Extract org_id from the JWT token payload returned by verify_token."
            ),
        },
        {
            "id": "no_stubs",
            "label": "No unimplemented stubs",
            "prompt_tmpl": (
                "Python code below. Are any function or method bodies left unimplemented? "
                "Look for: sole `pass`, `raise NotImplementedError`, `# TODO`, or `...` as body.\n"
                "Reply with exactly: PASS  or  FAIL\n"
                "If FAIL, add a second line: STUBS: <function names>\n\n"
                "Code:\n{code}"
            ),
            "correction": (
                "CORRECTION: All function bodies must be fully implemented. "
                "Replace every `pass`, `raise NotImplementedError`, and `# TODO` stub "
                "with working code that fulfils the function's purpose."
            ),
        },
    ]

    async def audit(self, code: str, domain: str = "general") -> Dict[str, Any]:
        """Run all checks and return consolidated results."""
        if not _is_enabled():
            return {"passed": True, "failures": [], "corrections": ""}

        # Fast static pre-checks run before any LLM calls
        from aether_os.core.council.council_reviewer import _static_security_checks
        static_issues = _static_security_checks(code)
        pre_failures = [
            {"check": "static_security", "label": issue, "detail": issue, "model": "static"}
            for issue in static_issues
        ]
        static_corrections = [
            "CORRECTION: Remove hardcoded secrets — use environment variables instead."
        ] if any("[Static] Secret leakage" in i for i in static_issues) else []

        from aether_os.core.llm.openrouter_client import call_openrouter, COUNCIL_MODELS

        # org_isolation is skipped only for purely static/non-multi-tenant domains.
        # Healthcare, fintech, education, and all SaaS variants must have it enforced.
        _ORG_ISOLATION_EXEMPT = frozenset({"static_site", "landing_page", "documentation"})
        checks = (
            [c for c in self._CHECKS if c["id"] != "org_isolation"]
            if domain in _ORG_ISOLATION_EXEMPT
            else self._CHECKS
        )

        # Trim code — council checks need structure, not every line.
        # 8 KB covers all route definitions in typical generated apps.
        code_snippet = code[:8000]

        failures: List[Dict[str, Any]] = []
        corrections: List[str] = []

        for i, check in enumerate(checks):
            # Rotate through council models so each check uses a different one
            model = COUNCIL_MODELS[i % len(COUNCIL_MODELS)]
            prompt = check["prompt_tmpl"].format(code=code_snippet)

            # Try each model in the council list; skip on 429/404 and move to next
            verdict_raw = None
            tried: List[str] = []
            for candidate in [model] + [m for m in COUNCIL_MODELS if m != model]:
                if candidate in tried:
                    continue
                tried.append(candidate)
                try:
                    verdict_raw = await call_openrouter(
                        prompt,
                        task_type="review",
                        system=(
                            "You are a strict code reviewer. Answer in exactly the format "
                            "requested — one word verdict, optional second line detail. "
                            "No prose, no markdown."
                        ),
                        max_tokens=150,
                        model=candidate,
                    )
                    model = candidate  # record which one succeeded
                    break
                except Exception as exc:
                    logger.warning(
                        "BackendAuditCouncil: check=%s model=%s failed — %s (trying next)",
                        check["id"], candidate, exc,
                    )

            if verdict_raw is None:
                logger.warning("BackendAuditCouncil: check=%s — all models failed, skipping", check["id"])
                continue

            lines = verdict_raw.strip().splitlines()
            verdict = lines[0].strip().upper()
            detail = lines[1].strip() if len(lines) > 1 else ""

            if "FAIL" in verdict:
                failures.append({
                    "check": check["id"],
                    "label": check["label"],
                    "detail": detail,
                    "model": model,
                })
                corrections.append(check["correction"])
                logger.warning(
                    "BackendAuditCouncil FAIL: check=%s via=%s detail=%s",
                    check["id"], model, detail,
                )
            else:
                logger.info(
                    "BackendAuditCouncil PASS: check=%s via=%s", check["id"], model
                )

        all_failures = pre_failures + failures
        all_corrections = static_corrections + corrections
        return {
            "passed": len(all_failures) == 0,
            "failures": all_failures,
            "corrections": "\n\n".join(all_corrections),
        }


class FrontendAuditCouncil:
    """
    Post-generation audit for p05 frontend output.
    Runs 3 checks on the generated TypeScript/TSX code.
    """

    _CHECKS = [
        {
            "id": "responsive_classes",
            "label": "Tailwind responsive classes present",
            "prompt_tmpl": (
                "React/TSX code below. Does it use Tailwind responsive prefixes "
                "(sm:, md:, lg:, xl:) for layout or sizing on at least 3 elements?\n"
                "Reply: PASS or FAIL\nIf FAIL: MISSING: <what's missing>\n\nCode:\n{code}"
            ),
            "correction": (
                "CORRECTION: Add Tailwind responsive prefixes (sm:, md:, lg:) to grids, "
                "flex containers, and text sizes so the UI is usable on mobile."
            ),
        },
        {
            "id": "aria_labels",
            "label": "ARIA labels on interactive elements",
            "prompt_tmpl": (
                "React/TSX code below. Do all buttons and form inputs have "
                "aria-label, aria-labelledby, or an associated <label>?\n"
                "Reply: PASS or FAIL\nIf FAIL: MISSING: <element description>\n\nCode:\n{code}"
            ),
            "correction": (
                "CORRECTION: Add aria-label to every icon-only button and associate "
                "every form input with a <label> element or aria-label attribute."
            ),
        },
        {
            "id": "loading_empty_states",
            "label": "Loading and empty state handling",
            "prompt_tmpl": (
                "React/TSX code below. Does the component handle both a loading state "
                "(spinner or skeleton) and an empty state (no data message or illustration) "
                "for its main data list or table?\n"
                "Reply: PASS or FAIL\nIf FAIL: MISSING: <loading|empty|both>\n\nCode:\n{code}"
            ),
            "correction": (
                "CORRECTION: Add an isLoading branch that shows a spinner or skeleton, "
                "and an isEmpty branch that shows an empty state illustration and CTA "
                "before rendering the data list."
            ),
        },
    ]

    async def audit(self, tsx_code: str) -> Dict[str, Any]:
        if not _is_enabled():
            return {"passed": True, "failures": [], "corrections": ""}

        from aether_os.core.llm.openrouter_client import call_openrouter, COUNCIL_MODELS
        code_snippet = tsx_code[:6000]
        failures: List[Dict[str, Any]] = []
        corrections: List[str] = []

        for i, check in enumerate(self._CHECKS):
            model = COUNCIL_MODELS[i % len(COUNCIL_MODELS)]
            prompt = check["prompt_tmpl"].format(code=code_snippet)
            verdict_raw = None
            tried: List[str] = []
            for candidate in [model] + [m for m in COUNCIL_MODELS if m != model]:
                if candidate in tried:
                    continue
                tried.append(candidate)
                try:
                    verdict_raw = await call_openrouter(
                        prompt,
                        task_type="review",
                        system=(
                            "You are a strict frontend code reviewer. "
                            "Reply in exactly the format requested. No prose."
                        ),
                        max_tokens=150,
                        model=candidate,
                    )
                    model = candidate
                    break
                except Exception as exc:
                    logger.warning(
                        "FrontendAuditCouncil: check=%s model=%s failed — %s",
                        check["id"], candidate, exc,
                    )

            if verdict_raw is None:
                continue

            lines = verdict_raw.strip().splitlines()
            verdict = lines[0].strip().upper()
            detail = lines[1].strip() if len(lines) > 1 else ""

            if "FAIL" in verdict:
                failures.append({
                    "check": check["id"],
                    "label": check["label"],
                    "detail": detail,
                    "model": model,
                })
                corrections.append(check["correction"])
                logger.warning("FrontendAuditCouncil FAIL: check=%s detail=%s", check["id"], detail)
            else:
                logger.info("FrontendAuditCouncil PASS: check=%s", check["id"])

        all_passed = len(failures) == 0
        return {
            "passed": all_passed,
            "failures": failures,
            "corrections": "\n".join(corrections),
        }


class DeliveryCouncil:
    """Validates pipeline output before delivery to the client."""

    async def run(
        self,
        run_id: str,
        project_name: str,
        domain: str,
        phases_results: Dict[str, Any],
        org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not _is_enabled():
            return _PASS_RESULT.copy()

        from aether_os.core.llm.client import get_llm_client
        client = get_llm_client()

        completed = [p for p, r in phases_results.items() if r.get("status") in ("passed", "completed")]
        failed = [p for p, r in phases_results.items() if r.get("status") in ("failed", "timeout")]
        summary = json.dumps({
            "completed": len(completed),
            "failed": len(failed),
            "phases": {k: v.get("status", "unknown") for k, v in phases_results.items()},
        }, indent=2)

        prompt = _DELIVERY_PROMPT_TMPL.format(
            project_name=project_name or run_id,
            domain=domain,
            phases_completed=len(completed),
            phases_summary=summary[:8000],
        )
        try:
            raw = await client.call(
                prompt,
                task_type="classify",
                system=_COUNCIL_SYSTEM,
                max_tokens=512,
                org_id=org_id,
            )
            result = _parse_council_response(raw)
            logger.info(
                "DeliveryCouncil: passed=%s score=%.2f reason=%s",
                result.get("passed"),
                result.get("score", 0.0),
                result.get("reason", ""),
            )
            return result
        except Exception as exc:
            logger.warning("DeliveryCouncil: LLM call failed — %s", exc)
            return _ERROR_RESULT.copy()
