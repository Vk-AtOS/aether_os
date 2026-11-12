"""Answers to the domain model's clarifying questions, recorded and fed back into the build.

s02's domain-IR extraction lists every field it could not infer (IRClarifyingQuestion). A person
answers them through POST /factory/runs/{id}/clarifying-answers; the answers are stored here, in
a gateway-owned file (never in the run directory, which generated code can write) and read by
the s02 stage on its next run:

  * p02b appends them to the requirement text the extraction prompts see, as authoritative;
  * after extraction they are applied deterministically: the question is closed, the field's
    confidence becomes 1.0, and the answer is kept in DomainIR.clarifications, which the saved
    domain_ir.json carries to every later stage (s03 backend, s04 frontend generate from it).

s03 consumes the IR, not the answers, so the stage that must re-run is s02.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from aether_os.core.domain_ir import DomainIR
from aether_os.core.projects import get_project_manager
from aether_os.core.run_app import preview_state
from aether_os.core.run_app.safe_fs import read_text_or_none

logger = logging.getLogger(__name__)

MAX_ANSWERS = 50
MAX_VALUE_CHARS = 2000
ANSWERS_FILE = "clarifying_answers.json"


class AnswersRejected(ValueError):
    """The submitted answers do not match the stored questions (the router maps this to 422)."""


def stored_questions(project_id: str) -> List[Dict[str, Any]]:
    """The questions s02 saved for this run ([] when s02 has not produced any)."""
    root = get_project_manager().get_project_dir(project_id)
    summary = root / "s02_architecture" / "s02_architecture.json"
    text = read_text_or_none(root, summary)   # a planted link reads as "no questions", never a 500
    if text is None:
        return []
    try:
        questions = json.loads(text).get("clarifying_questions") or []
    except (OSError, ValueError, AttributeError) as exc:
        logger.warning("clarifying: unreadable question file %s: %s", summary, exc)
        return []
    return [q for q in questions if isinstance(q, dict) and q.get("field_path")]


def validate(questions: List[Dict[str, Any]], answers: Dict[str, Any]) -> Dict[str, str]:
    """Answers keyed by a stored question's field_path; options are enforced; sizes are capped."""
    if not isinstance(answers, dict) or not answers:
        raise AnswersRejected("answers must be a non-empty object {field_path: value}")
    if len(answers) > MAX_ANSWERS:
        raise AnswersRejected(f"at most {MAX_ANSWERS} answers per request")
    by_path = {q["field_path"]: q for q in questions}
    clean: Dict[str, str] = {}
    for path, value in answers.items():
        if path not in by_path:
            raise AnswersRejected(f"{str(path)[:80]!r} is not an open question of this run")
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise AnswersRejected(f"answer for {path} must be text or a number")
        text = str(value).strip()
        if not text:
            raise AnswersRejected(f"answer for {path} is empty")
        if len(text) > MAX_VALUE_CHARS:
            raise AnswersRejected(f"answer for {path} is longer than {MAX_VALUE_CHARS} characters")
        options = by_path[path].get("options") or []
        if options and text not in options:
            raise AnswersRejected(f"answer for {path} must be one of: {', '.join(map(str, options))}")
        clean[path] = text
    return clean


def digest(answers: Dict[str, str]) -> str:
    """What the ledger records instead of the answer text."""
    return hashlib.sha256(json.dumps(answers, sort_keys=True).encode()).hexdigest()


def _path(run_id: str) -> Path:
    return preview_state.state_dir(run_id) / ANSWERS_FILE


def load_answers(run_id: str) -> Dict[str, str]:
    path = preview_state.state_path(run_id).with_name(ANSWERS_FILE)  # no directory is created to read
    try:
        data = json.loads(path.read_text()) if path.is_file() else {}
    except (OSError, ValueError) as exc:
        logger.warning("clarifying: unreadable answers for run %s: %s", run_id, exc)
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


def save_answers(run_id: str, answers: Dict[str, str]) -> Dict[str, str]:
    """Merge into the run's recorded answers (a later answer replaces an earlier one); atomic write."""
    merged = {**load_answers(run_id), **answers}
    path = _path(run_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, indent=2))
    os.replace(tmp, path)
    return merged


def requirement_suffix(answers: Dict[str, str]) -> str:
    if not answers:
        return ""
    lines = "\n".join(f"- {path}: {value}" for path, value in sorted(answers.items()))
    return ("\n\nCLARIFICATIONS FROM THE REQUESTER (authoritative; they settle the ambiguity "
            f"about these fields, do not guess otherwise):\n{lines}\n")


def apply_to_ir(ir: DomainIR, answers: Dict[str, str]) -> List[str]:
    """Close the answered questions on the IR; returns the field paths that were applied."""
    applied: List[str] = []
    for path, value in answers.items():
        ir.clarifications[path] = value
        entity_name, _, field_name = path.partition(".")
        entity = ir.get_entity(entity_name)
        for f in (entity.fields if entity else []):
            if f.name == field_name:
                f.confidence = 1.0
        ir.clarifying_questions = [q for q in ir.clarifying_questions if q.field_path != path]
        applied.append(path)
    return applied
