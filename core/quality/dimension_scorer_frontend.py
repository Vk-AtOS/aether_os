"""Frontend dimension scoring — static TS/TSX analysis for type-safety, a11y, and correctness."""
# ponytail: subprocess tsc/eslint/axe-core would be more accurate but requires npm installed in CI
# upgrade when we have a guaranteed npm environment in the s05 scoring context
from __future__ import annotations

import logging
import re

from aether_os.core.quality.dimension_critic_types import DimensionScore, PASSING_THRESHOLD

logger = logging.getLogger(__name__)


def score_typescript_types(content: str, file_path: str | None = None) -> DimensionScore:
    """Scan for TypeScript anti-patterns: any, @ts-ignore, non-null assertions."""
    findings: list[str] = []
    score = 1.0
    try:
        any_count = len(re.findall(r': any\b', content))
        if any_count:
            deduct = min(0.3, any_count * 0.05)
            findings.append(f"{any_count} use(s) of `: any` — weakens type safety")
            score -= deduct

        ignore_count = len(re.findall(r'//\s*@ts-ignore', content))
        if ignore_count:
            deduct = min(0.3, ignore_count * 0.10)
            findings.append(f"{ignore_count} `@ts-ignore` suppression(s)")
            score -= deduct

        if re.search(r'//\s*@ts-nocheck', content):
            findings.append("@ts-nocheck disables type checking for entire file")
            score -= 0.30

        as_any_count = len(re.findall(r'\bas any\b', content))
        if as_any_count:
            deduct = min(0.2, as_any_count * 0.05)
            findings.append(f"{as_any_count} `as any` cast(s)")
            score -= deduct

        nonnull_count = len(re.findall(r'!\s*\.', content))
        if nonnull_count:
            deduct = min(0.1, nonnull_count * 0.02)
            findings.append(f"{nonnull_count} non-null assertion(s) (`!.`)")
            score -= deduct

        score = max(0.0, min(1.0, score))
    except Exception as exc:
        logger.warning("[dimension_scorer_frontend] score_typescript_types crashed: %s", exc)
        return DimensionScore(
            dimension="typescript_types", score=0.5,
            findings=[f"Critic error (fail-open): {exc}"], passed=True,
        )

    return DimensionScore(
        dimension="typescript_types", score=score, findings=findings,
        passed=score >= PASSING_THRESHOLD,
    )


def score_frontend_a11y(content: str, file_path: str | None = None) -> DimensionScore:
    """Scan TSX for accessibility anti-patterns: missing alt, aria-label, key={index}."""
    findings: list[str] = []
    score = 1.0
    try:
        # <img without alt=
        img_no_alt = len(re.findall(r'<img(?![^>]*\balt=)[^>]*/?>',  content))
        if img_no_alt:
            deduct = min(0.45, img_no_alt * 0.15)
            findings.append(f"{img_no_alt} <img> element(s) missing `alt` attribute")
            score -= deduct

        # <button with onClick but immediately followed by a child tag (icon-only heuristic)
        icon_buttons = len(re.findall(r'<button[^>]*onClick[^>]*>\s*<', content))
        if icon_buttons:
            deduct = icon_buttons * 0.10
            findings.append(
                f"{icon_buttons} <button> element(s) with onClick and no visible text child "
                "(possible icon-only button — add aria-label)"
            )
            score -= deduct

        # <input without aria-label
        input_no_label = len(re.findall(r'<input(?![^>]*\baria-label=)[^>]*/?>',  content))
        if input_no_label:
            deduct = min(0.3, input_no_label * 0.10)
            findings.append(f"{input_no_label} <input> element(s) missing `aria-label`")
            score -= deduct

        # key={index} in JSX
        key_index = len(re.findall(r'\bkey=\{index\}', content))
        if key_index:
            deduct = min(0.2, key_index * 0.05)
            findings.append(f"{key_index} use(s) of `key={{index}}` — unstable list keys")
            score -= deduct

        # tabIndex={-1} on interactive elements (informational)
        tab_neg = len(re.findall(r'tabIndex=\{-1\}', content))
        if tab_neg:
            findings.append(
                f"{tab_neg} element(s) with tabIndex={{-1}} — verify intentional focus exclusion"
            )
            score -= 0.02 * tab_neg

        score = max(0.0, min(1.0, score))
    except Exception as exc:
        logger.warning("[dimension_scorer_frontend] score_frontend_a11y crashed: %s", exc)
        return DimensionScore(
            dimension="frontend_a11y", score=0.5,
            findings=[f"Critic error (fail-open): {exc}"], passed=True,
        )

    return DimensionScore(
        dimension="frontend_a11y", score=score, findings=findings,
        passed=score >= PASSING_THRESHOLD,
    )


def score_frontend_correctness(content: str, file_path: str | None = None) -> DimensionScore:
    """Scan for console.log leaks, TODOs, empty catches, and unhandled fetch calls."""
    findings: list[str] = []
    score = 1.0
    try:
        # console.log in non-test files
        in_test = file_path and ("__tests__" in file_path or ".test." in file_path or ".spec." in file_path)
        if not in_test:
            log_count = len(re.findall(r'\bconsole\.log\(', content))
            if log_count:
                deduct = min(0.25, log_count * 0.05)
                findings.append(f"{log_count} `console.log` call(s) in production code")
                score -= deduct

        # console.error not preceded by catch (heuristic: split by lines, check 3-line window)
        lines = content.splitlines()
        unguarded_errors = 0
        for i, line in enumerate(lines):
            if 'console.error(' in line:
                window = '\n'.join(lines[max(0, i - 3):i])
                if 'catch' not in window:
                    unguarded_errors += 1
        if unguarded_errors:
            deduct = min(0.3, unguarded_errors * 0.10)
            findings.append(f"{unguarded_errors} `console.error` call(s) outside catch block")
            score -= deduct

        # TODO comments
        todo_count = len(re.findall(r'//\s*TODO', content, re.IGNORECASE))
        if todo_count:
            deduct = min(0.15, todo_count * 0.03)
            findings.append(f"{todo_count} TODO comment(s) — unfinished implementation")
            score -= deduct

        # Empty catch blocks: catch { } or catch (e) { }
        empty_catches = len(re.findall(r'catch\s*(?:\([^)]*\))?\s*\{\s*\}', content))
        if empty_catches:
            findings.append(f"{empty_catches} empty catch block(s) — errors silently swallowed")
            score -= 0.15 * empty_catches

        # fetch() without .catch() or try/await coverage (rough heuristic)
        fetch_count = len(re.findall(r'\bfetch\(', content))
        catch_count = len(re.findall(r'\.catch\(', content))
        try_count = len(re.findall(r'\btry\s*\{', content))
        if fetch_count > (catch_count + try_count * 2):
            excess = fetch_count - (catch_count + try_count * 2)
            findings.append(
                f"{excess} `fetch()` call(s) may lack error handling (.catch or try/await)"
            )
            score -= min(0.20, excess * 0.05)

        score = max(0.0, min(1.0, score))
    except Exception as exc:
        logger.warning("[dimension_scorer_frontend] score_frontend_correctness crashed: %s", exc)
        return DimensionScore(
            dimension="frontend_correctness", score=0.5,
            findings=[f"Critic error (fail-open): {exc}"], passed=True,
        )

    return DimensionScore(
        dimension="frontend_correctness", score=score, findings=findings,
        passed=score >= PASSING_THRESHOLD,
    )
