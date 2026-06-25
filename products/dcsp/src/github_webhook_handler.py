"""Handles GitHub App webhook events and triggers autonomous fix pipeline."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

from src.validators.language_validators import collect_errors as _collect_errors

logger = logging.getLogger(__name__)

# All file extensions that DCSP can validate and auto-repair.
SUPPORTED_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".go", ".rb",
    ".java", ".rs", ".php", ".c", ".h", ".cpp", ".cc", ".cxx",
}


def collect_all_errors(content: str, file_path: str) -> list[str]:
    """Detect language from extension and run the appropriate validator."""
    return _collect_errors(content, file_path)


def _broadcast_job(job: dict) -> None:
    """Fire-and-forget WebSocket broadcast from a sync context."""
    try:
        from src.api.websocket_manager import MANAGER
        import threading

        def _run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(MANAGER.broadcast_job_update("new_job", job))
            finally:
                loop.close()

        threading.Thread(target=_run, daemon=True).start()
    except Exception as e:
        logger.warning("WebSocket broadcast failed: %s", e)


async def handle_push_event(payload: dict[str, Any], db: Any) -> dict:
    """
    On push: fetch each changed .py file, scan for syntax errors, and run the
    repair pipeline on every file that fails ast.parse().
    Results appear in the Live Feed immediately via WebSocket.
    """
    repo_full_name = payload.get("repository", {}).get("full_name", "")
    installation_id = payload.get("installation", {}).get("id")
    ref = payload.get("ref", "")
    commits = payload.get("commits", [])
    head_sha = payload.get("after", "")

    if not installation_id:
        return {"status": "skipped", "reason": "no installation_id"}

    branch = ref.replace("refs/heads/", "")
    if branch not in ("main", "master", "develop", "dev"):
        return {"status": "skipped", "reason": f"branch '{branch}' not monitored"}

    # Collect unique changed source files across all commits (all supported languages)
    changed: set[str] = set()
    for commit in commits:
        for f in commit.get("modified", []) + commit.get("added", []):
            if any(f.endswith(ext) for ext in SUPPORTED_EXTS):
                changed.add(f)

    if not changed:
        return {"status": "skipped", "reason": "no supported source files changed"}

    logger.info("Push to %s/%s — scanning %d source files", repo_full_name, branch, len(changed))

    from src.github_app import get_repo_file
    from src.pipeline import run_repair
    from src.api.state import add_job_to_history

    repaired = 0
    errors_found = 0

    for file_path in changed:
        content = get_repo_file(installation_id, repo_full_name, file_path, ref=head_sha or branch)
        if not content:
            logger.warning("Could not fetch %s from %s", file_path, repo_full_name)
            continue

        # Syntax check — collect ALL errors, not just the first one
        errors = collect_all_errors(content, file_path)
        if not errors:
            continue  # File is clean
        errors_found += len(errors)
        # Format as a traceback-style log so pipeline's parse_log() can extract
        # stack frames. Each error line from collect_all_errors has the form:
        #   'File "path", line N: SyntaxError: msg'
        # Reformat to Python traceback style.
        trace_lines = ["Traceback (most recent call last):"]
        for err in errors:
            # Parse: File "path", line N: ExcType: msg
            import re as _re_err
            m = _re_err.match(r'File "([^"]+)", line (\d+): (\w+): (.+)', err)
            if m:
                trace_lines.append(f'  File "{m.group(1)}", line {m.group(2)}, in <module>')
                trace_lines.append(f"    {m.group(3)}: {m.group(4)}")
            else:
                trace_lines.append(f"  {err}")
        # Put the primary exception type at the end (what parse_log looks for)
        first_err = errors[0]
        m0 = _re_err.match(r'File "([^"]+)", line (\d+): (\w+): (.+)', first_err)
        if m0:
            trace_lines.append(f"{m0.group(3)}: {m0.group(4)}")
        log_content = "\n".join(trace_lines)
        logger.info("%d error(s) in %s — running repair", len(errors), file_path)

        # Write fetched file to a temp dir so the LLM gets full file context
        # and the test runner doesn't accidentally run DCSP's own tests.
        import tempfile, os as _os
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = _os.path.join(tmp_dir, file_path)
            _os.makedirs(_os.path.dirname(tmp_path), exist_ok=True)
            with open(tmp_path, "w") as _f:
                _f.write(content)

            result = run_repair(
                log_content=log_content,
                root_dir=tmp_dir,
                historical_records=[],
                ast_index=None,
                call_graph=None,
            )

        # ── Fix 2+3: Post-patch validation and real confidence scoring ─────────
        # Apply the patch to a temp copy and verify the result parses BEFORE
        # marking success or creating a PR.  This catches hunk-offset bugs where
        # `patch --fuzz=3` silently applies hunks to the wrong lines.
        _computed_confidence = result.confidence
        _sandbox_label = getattr(result, "sandbox_result", None)

        if result.success and result.patch_diff:
            from src.sandbox.venv_runner import run_patch_in_sandbox
            _sb = run_patch_in_sandbox(content, result.patch_diff, file_path)
            _sandbox_label = "passed" if _sb["success"] else f"failed: {_sb['message']}"

            if _sb["success"]:
                logger.info("Post-patch validation PASSED for %s", file_path)
                # Compute real confidence: fraction of errors eliminated
                _errors_before = len(errors)
                try:
                    _remaining = collect_all_errors(_sb["validated_content"] or "", file_path)
                    _errors_after = len(_remaining)
                except Exception as _ce:
                    logger.warning("Error counting residual errors: %s", _ce)
                    _errors_after = 0
                _computed_confidence = round(
                    max(0.0, 1.0 - (_errors_after / max(_errors_before, 1))), 2
                )
            else:
                logger.warning(
                    "Post-patch validation FAILED for %s: %s", file_path, _sb["message"]
                )
                # Override result — patch doesn't actually fix the file
                import dataclasses as _dc
                result = _dc.replace(
                    result,
                    success=False,
                    escalated=True,
                    explanation=(
                        "LLM patch generated but post-patch validation failed — "
                        "file still has syntax errors after applying diff. "
                        "Escalated for manual review."
                    ),
                    confidence=0.0,
                )
                _computed_confidence = 0.0

        job: dict = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "repo_name": repo_full_name,
            "branch": branch,
            "ci_system": "github_push",
            "detected_language": result.detected_language,
            "success": result.success,
            "confidence": _computed_confidence,  # real score, not LLM self-report
            "escalated": result.escalated,
            "explanation": result.explanation,
            "patch_diff": result.patch_diff,
            "slm_generated": result.slm_generated,
            "violations": result.violations,
            "source": result.source,
            "fingerprint": result.fingerprint,
            "sandbox_result": _sandbox_label,
        }
        add_job_to_history(job)
        _broadcast_job(job)

        if result.success:
            repaired += 1
            # Attempt to open a PR with the validated fix
            try:
                import re as _re
                from src.github_app import create_fix_pr, get_existing_dcsp_pr

                # Use the sandbox-validated content when available; fall back to
                # the patch+fallback pipeline for non-Python or edge cases.
                fixed_content: str | None = None

                if result.patch_diff and content:
                    from src.sandbox.venv_runner import run_patch_in_sandbox as _rps
                    _fb = _rps(content, result.patch_diff, file_path)
                    if _fb["success"]:
                        fixed_content = _fb["validated_content"]
                    else:
                        # Fallback: pair each removed line with the corresponding
                        # added line and do direct string replacement.
                        # Handles LLM diffs with wrong context/filename.
                        _removes: list[str] = []
                        _adds: list[str] = []
                        for _dl in result.patch_diff.splitlines():
                            if _dl.startswith("-") and not _dl.startswith("---"):
                                _removes.append(_dl[1:])
                            elif _dl.startswith("+") and not _dl.startswith("+++"):
                                _adds.append(_dl[1:])
                        _candidate = content
                        _changed = False
                        for _old, _new in zip(_removes, _adds):
                            if _old in _candidate:
                                _candidate = _candidate.replace(_old, _new, 1)
                                _changed = True
                        if _changed:
                            fixed_content = _candidate
                            logger.info(
                                "patch fallback: direct substitution succeeded for %s", file_path
                            )
                        else:
                            logger.warning(
                                "patch and fallback both failed for %s diff=%s",
                                file_path, result.patch_diff[:200],
                            )

                if fixed_content:
                    fix_branch = _re.sub(
                        r"[^a-z0-9-]", "-",
                        f"dcsp-fix-{file_path.replace('/', '-').lower()}"
                    ).strip("-")[:60]

                    # ── Fix 4: PR deduplication ────────────────────────────────
                    pr_url: str | None = None
                    existing_pr = get_existing_dcsp_pr(
                        installation_id, repo_full_name, fix_branch
                    )
                    if existing_pr:
                        logger.info(
                            "Skipping PR creation — open DCSP PR already exists: %s",
                            existing_pr,
                        )
                        pr_url = existing_pr
                    else:
                        pr_url = create_fix_pr(
                            installation_id=installation_id,
                            repo_full_name=repo_full_name,
                            base_branch=branch,
                            fix_branch=fix_branch,
                            file_path=file_path,
                            original_content=content,
                            fixed_content=fixed_content,
                            commit_message=f"fix: auto-repair SyntaxError in {file_path} [DCSP]",
                            pr_title=f"[DCSP] Auto-fix: SyntaxError in {file_path}",
                            pr_body=(
                                f"DCSP detected and auto-repaired a `SyntaxError` in `{file_path}`.\n\n"
                                f"**Confidence:** {_computed_confidence:.0%}\n\n"
                                f"```diff\n{result.patch_diff}\n```\n\n"
                                f"_Review before merging._"
                            ),
                        )

                    if pr_url:
                        job["approved_pr_url"] = pr_url
                        logger.info("Fix PR: %s", pr_url)
            except Exception as e:
                logger.warning("PR creation failed: %s", e)

        # ── Fix 5: Persist to DB AFTER PR creation so pr_url and sandbox_result are saved ──
        try:
            from src.db.job_repo import save_job
            from src.database import SessionLocal
            _db = SessionLocal()
            try:
                save_job(_db, job)
            finally:
                _db.close()
        except Exception as _dbe:
            logger.warning("Failed to persist push repair job to DB: %s", _dbe)

    return {
        "status": "processed",
        "repo": repo_full_name,
        "branch": branch,
        "files_scanned": len(changed),
        "errors_found": errors_found,
        "repaired": repaired,
    }


async def handle_check_run_event(payload: dict[str, Any], db: Any) -> dict:
    """
    On check_run failure: extract the error text from annotations/output and
    run the repair pipeline. Broadcasts results to the Live Feed.
    """
    action = payload.get("action", "")
    check_run = payload.get("check_run", {})
    conclusion = check_run.get("conclusion", "")

    if action != "completed" or conclusion not in ("failure", "timed_out"):
        return {"status": "skipped"}

    repo_full_name = payload.get("repository", {}).get("full_name", "")
    installation_id = payload.get("installation", {}).get("id")
    branch = check_run.get("check_suite", {}).get("head_branch", "main")

    # Build a log string from the check run output/annotations
    output = check_run.get("output", {})
    summary = output.get("summary", "") or ""
    text = output.get("text", "") or ""
    annotations = output.get("annotations", []) or []

    annotation_lines = "\n".join(
        f'  File "{a.get("path", "?")}", line {a.get("start_line", 0)}\n    {a.get("message", "")}'
        for a in annotations[:10]
    )
    log_content = f"{summary}\n{text}\n{annotation_lines}".strip()

    if not log_content:
        log_content = f"CI check '{check_run.get('name', 'CI')}' failed on {repo_full_name}"

    logger.info("Check run failed on %s — running repair pipeline", repo_full_name)

    from src.pipeline import run_repair
    from src.api.state import add_job_to_history

    result = run_repair(
        log_content=log_content,
        root_dir=".",
        historical_records=[],
        ast_index=None,
        call_graph=None,
    )

    job: dict = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat(),
        "repo_name": repo_full_name,
        "branch": branch,
        "ci_system": "github_check_run",
        "detected_language": result.detected_language,
        "success": result.success,
        "confidence": result.confidence,
        "escalated": result.escalated,
        "explanation": result.explanation,
        "patch_diff": result.patch_diff,
        "slm_generated": result.slm_generated,
        "violations": result.violations,
        "source": result.source,
        "fingerprint": result.fingerprint,
        "sandbox_result": getattr(result, "sandbox_result", None),
    }
    add_job_to_history(job)
    _broadcast_job(job)

    return {"status": "repaired" if result.success else "escalated", "repo": repo_full_name}


async def handle_installation_webhook_event(payload: dict[str, Any], db: Any) -> dict:
    """Persist GitHub App installation / uninstallation to DB."""
    action = payload.get("action", "")
    installation = payload.get("installation", {})
    installation_id = installation.get("id")
    account = installation.get("account", {})
    account_login = account.get("login", "unknown")
    account_type = account.get("type", "User")

    if not installation_id:
        return {"status": "skipped", "reason": "no installation_id in payload"}

    if action == "created":
        try:
            from src.db.github_installation_repo import upsert_installation
            upsert_installation(db=db, installation_id=installation_id,
                                account_login=account_login, account_type=account_type)
        except Exception as e:
            logger.error("Failed to persist GitHub installation %s: %s", installation_id, e)
        logger.info("GitHub App installed for %s (id=%s)", account_login, installation_id)
        return {"status": "installed", "installation_id": installation_id}

    if action == "deleted":
        try:
            from src.db.github_installation_repo import deactivate_installation
            deactivate_installation(db=db, installation_id=installation_id)
        except Exception as e:
            logger.error("Failed to deactivate GitHub installation %s: %s", installation_id, e)
        logger.info("GitHub App uninstalled for %s (id=%s)", account_login, installation_id)
        return {"status": "uninstalled", "installation_id": installation_id}

    return {"status": "ignored", "action": action}
