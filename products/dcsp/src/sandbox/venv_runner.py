"""Lightweight Python sandbox using subprocess — no Docker required."""
from __future__ import annotations

import ast
import logging
import os
import re
import subprocess
import tempfile

logger = logging.getLogger(__name__)


def validate_python_syntax(content: str, filename: str = "file.py") -> dict:
    """Run syntax check on Python content. Returns {valid, errors, message}."""
    try:
        ast.parse(content)
        return {"valid": True, "errors": [], "message": "Syntax OK"}
    except SyntaxError as e:
        return {
            "valid": False,
            "errors": [f"line {e.lineno}: {e.msg}"],
            "message": str(e),
        }


def run_patch_in_sandbox(
    original_content: str, patch_diff: str, file_path: str
) -> dict:
    """
    Apply patch in a temp directory, run syntax check on result.
    Returns: {success, validated_content, errors, message}
    """
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, file_path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w") as f:
            f.write(original_content)

        # Normalize diff headers so `patch -p1` can find the file
        norm = re.sub(
            r"^--- .*$", f"--- a/{file_path}", patch_diff, count=1, flags=re.MULTILINE
        )
        norm = re.sub(
            r"^\+\+\+ .*$",
            f"+++ b/{file_path}",
            norm,
            count=1,
            flags=re.MULTILINE,
        )

        patch_file = os.path.join(tmp, "fix.patch")
        with open(patch_file, "w") as f:
            f.write(norm)

        try:
            r = subprocess.run(
                ["patch", "-p1", "--fuzz=3", "--ignore-whitespace", "-i", patch_file],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception as e:
            logger.warning("venv_runner: patch subprocess error for %s: %s", file_path, e)
            return {
                "success": False,
                "validated_content": None,
                "errors": [str(e)],
                "message": f"patch subprocess error: {e}",
            }

        if r.returncode != 0:
            # patch command failed — try direct line-by-line substitution as fallback.
            # This handles malformed hunks (wrong offsets, missing context lines) that
            # the LLM sometimes produces while the individual +/- lines are still correct.
            logger.info("venv_runner: patch failed for %s — trying direct substitution fallback", file_path)
            removes = []
            adds = []
            for dl in patch_diff.splitlines():
                if dl.startswith("-") and not dl.startswith("---"):
                    removes.append(dl[1:])
                elif dl.startswith("+") and not dl.startswith("+++"):
                    adds.append(dl[1:])
            candidate = original_content
            changed = False
            for old_line, new_line in zip(removes, adds):
                if old_line in candidate:
                    candidate = candidate.replace(old_line, new_line, 1)
                    changed = True
            if changed:
                syntax = validate_python_syntax(candidate, file_path)
                if syntax["valid"]:
                    logger.info("venv_runner: direct substitution PASSED for %s", file_path)
                    return {
                        "success": True,
                        "validated_content": candidate,
                        "errors": [],
                        "message": "Syntax validation passed (via direct substitution fallback)",
                    }
                else:
                    logger.warning("venv_runner: direct substitution applied but file still broken: %s", syntax["message"])
                    return {
                        "success": False,
                        "validated_content": None,
                        "errors": syntax["errors"],
                        "message": f"Post-patch syntax error (fallback): {syntax['message']}",
                    }
            return {
                "success": False,
                "validated_content": None,
                "errors": [r.stderr[:500]],
                "message": "patch command failed",
            }

        try:
            result_content = open(target).read()
        except Exception as e:
            logger.warning("venv_runner: could not read patched file %s: %s", target, e)
            return {
                "success": False,
                "validated_content": None,
                "errors": [str(e)],
                "message": f"could not read patched file: {e}",
            }

        syntax = validate_python_syntax(result_content, file_path)

        return {
            "success": syntax["valid"],
            "validated_content": result_content if syntax["valid"] else None,
            "errors": syntax["errors"],
            "message": (
                "Syntax validation passed"
                if syntax["valid"]
                else f"Post-patch syntax error: {syntax['message']}"
            ),
        }
