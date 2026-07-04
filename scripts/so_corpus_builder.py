#!/usr/bin/env python3
"""
Stack Overflow FastAPI/SQLAlchemy Bug→Fix Corpus Builder.

Downloads the SO data dump from archive.org, filters posts tagged with
fastapi OR sqlalchemy, extracts accepted-answer pairs, and stores them
in core/knowledge_graph/golden_examples/so_bugfix_examples.json.

Usage:
    python3 scripts/so_corpus_builder.py [--dry-run] [--limit 500] [--output PATH]

The data dump is large (XML, ~15GB). This script uses streaming XML parsing
(xml.etree.ElementTree.iterparse) to avoid loading everything into memory.
The relevant tags are about 2% of total, so memory usage stays low.
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from xml.etree.ElementTree import iterparse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("so_corpus_builder")

# ── Constants ──────────────────────────────────────────────────────────────────

POSTS_URL = (
    "https://archive.org/download/stackexchange/stackoverflow.com-Posts.7z"
)
# Smaller test mirror: the 2GB "meta" dump is easier to test with
POSTS_URL_META = (
    "https://archive.org/download/stackexchange/meta.stackoverflow.com.7z"
)

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_OUTPUT = (
    REPO_ROOT / "core" / "knowledge_graph" / "golden_examples" / "so_bugfix_examples.json"
)
CACHE_PATH = REPO_ROOT / ".so_cache" / "Posts.xml"

TARGET_TAGS = {"fastapi", "sqlalchemy", "pydantic", "alembic"}

# Mapping SO tag → our internal bug_class label
TAG_TO_CLASS: dict[str, str] = {
    "fastapi":    "FASTAPI",
    "sqlalchemy": "SQLALCHEMY",
    "pydantic":   "PYDANTIC",
    "alembic":    "ALEMBIC",
}

# ── Argument parsing ───────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip download; use any cached Posts.xml at .so_cache/Posts.xml",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum number of bug→fix pairs to extract (default: 500)",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output JSON path (default: {DEFAULT_OUTPUT})",
    )
    p.add_argument(
        "--meta",
        action="store_true",
        help="Use the smaller meta.stackoverflow.com dump for testing",
    )
    return p.parse_args()


# ── Download helpers ───────────────────────────────────────────────────────────


def _ensure_7z_available() -> bool:
    """Return True if the `7z` binary is on PATH."""
    import shutil
    return shutil.which("7z") is not None or shutil.which("7zz") is not None


def _download_with_progress(url: str, dest: Path) -> None:
    """Download *url* to *dest* with a simple progress display."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading %s → %s", url, dest)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "so-corpus-builder/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk = 1 << 20  # 1 MB
            archive_path = dest.with_suffix(".7z")
            with open(archive_path, "wb") as fh:
                while True:
                    data = resp.read(chunk)
                    if not data:
                        break
                    fh.write(data)
                    downloaded += len(data)
                    if total:
                        pct = downloaded * 100 // total
                        logger.info("  %d%% (%d MB / %d MB)", pct, downloaded >> 20, total >> 20)
    except urllib.error.URLError as exc:
        logger.error("Download failed: %s", exc)
        raise

    # Extract the .7z archive
    _extract_7z(archive_path, dest.parent)


def _extract_7z(archive: Path, dest_dir: Path) -> None:
    """Extract a .7z archive to dest_dir."""
    import subprocess
    cmd = ["7z", "e", str(archive), "-o" + str(dest_dir), "Posts.xml", "-y"]
    logger.info("Extracting %s …", archive)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if result.returncode != 0:
            logger.error("7z stderr: %s", result.stderr)
            raise RuntimeError(f"7z extraction failed (code {result.returncode})")
        logger.info("Extraction complete.")
    except FileNotFoundError:
        logger.error(
            "7z binary not found. Install p7zip-full (apt) or p7zip (brew) to extract the archive."
        )
        raise


def _ensure_posts_xml(dry_run: bool, use_meta: bool) -> Path:
    """Return path to Posts.xml, downloading and extracting if needed."""
    if CACHE_PATH.exists():
        logger.info("Using cached Posts.xml at %s", CACHE_PATH)
        return CACHE_PATH

    if dry_run:
        raise FileNotFoundError(
            f"--dry-run requested but no cached file found at {CACHE_PATH}. "
            "Run without --dry-run first to download the dump."
        )

    if not _ensure_7z_available():
        raise EnvironmentError(
            "7z is required to extract the SO data dump. "
            "Install with: brew install p7zip  OR  apt-get install p7zip-full"
        )

    url = POSTS_URL_META if use_meta else POSTS_URL
    _download_with_progress(url, CACHE_PATH)
    return CACHE_PATH


# ── XML parsing ────────────────────────────────────────────────────────────────


def _parse_tags(raw: str) -> list[str]:
    """Convert SO tag string '<python><fastapi>' → ['python', 'fastapi']."""
    return re.findall(r"<([^>]+)>", raw)


def _strip_html(text: str) -> str:
    """Remove HTML tags and unescape entities. Keeps code blocks inline."""
    # Replace <code> blocks with backtick fences for readability
    text = re.sub(r"<pre><code>(.*?)</code></pre>", r"\n```\n\1\n```\n", text, flags=re.DOTALL)
    text = re.sub(r"<code>(.*?)</code>", r"`\1`", text, flags=re.DOTALL)
    # Remove remaining HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(text).strip()


def _extract_code_snippet(body: str) -> str:
    """Extract the first code block from an SO post body."""
    match = re.search(r"```(.*?)```", body, re.DOTALL)
    if match:
        return match.group(1).strip()[:800]
    return ""


def _has_target_tag(tags: list[str]) -> bool:
    return bool(TARGET_TAGS.intersection(tags))


def _primary_bug_class(tags: list[str]) -> str:
    for tag in tags:
        cls = TAG_TO_CLASS.get(tag)
        if cls:
            return cls
    return "FASTAPI"


def _stream_questions_and_answers(
    posts_path: Path,
    limit: int,
) -> list[dict]:
    """
    Stream Posts.xml and collect accepted-answer pairs.

    Memory usage: we keep only questions with AcceptedAnswerId and answers
    whose Id appears in that set. Questions dict stays bounded by the limit
    requested plus some overshoot.
    """
    logger.info("Streaming %s …", posts_path)

    # First pass: collect qualifying questions (PostTypeId=1)
    questions: dict[str, dict] = {}
    answer_ids_needed: set[str] = set()
    post_count = 0

    try:
        for _event, elem in iterparse(str(posts_path), events=("end",)):
            if elem.tag != "row":
                elem.clear()
                continue

            post_count += 1
            if post_count % 500_000 == 0:
                logger.info("  Scanned %d posts, %d questions matched so far …",
                            post_count, len(questions))

            post_type = elem.get("PostTypeId")
            if post_type == "1":
                accepted = elem.get("AcceptedAnswerId")
                raw_tags = elem.get("Tags", "")
                tags = _parse_tags(raw_tags)
                if accepted and _has_target_tag(tags):
                    qid = elem.get("Id")
                    questions[qid] = {
                        "title": elem.get("Title", ""),
                        "body": _strip_html(elem.get("Body", "")),
                        "tags": tags,
                        "score": int(elem.get("Score", "0")),
                        "accepted_answer_id": accepted,
                        "link": f"https://stackoverflow.com/q/{qid}",
                    }
                    answer_ids_needed.add(accepted)
                    if len(questions) >= limit * 3:
                        logger.info("  Collected enough question candidates, stopping pass 1.")
                        elem.clear()
                        break

            elem.clear()

    except StopIteration:
        pass

    logger.info("Pass 1 complete: %d qualifying questions found.", len(questions))

    # Second pass: collect accepted answers
    answers: dict[str, str] = {}

    try:
        for _event, elem in iterparse(str(posts_path), events=("end",)):
            if elem.tag != "row":
                elem.clear()
                continue

            post_type = elem.get("PostTypeId")
            if post_type == "2":
                aid = elem.get("Id")
                if aid in answer_ids_needed:
                    answers[aid] = _strip_html(elem.get("Body", ""))
                    answer_ids_needed.discard(aid)
                    if not answer_ids_needed:
                        elem.clear()
                        break

            elem.clear()

    except StopIteration:
        pass

    logger.info("Pass 2 complete: %d answers matched.", len(answers))

    # Combine into examples
    examples = []
    idx = 1
    for _qid, q in sorted(questions.items(), key=lambda kv: -kv[1]["score"]):
        aid = q["accepted_answer_id"]
        if aid not in answers:
            continue

        answer_text = answers[aid]
        bad_code = _extract_code_snippet(q["body"])
        fix_code = _extract_code_snippet(answer_text)

        examples.append({
            "id": f"so_{idx:04d}",
            "type": "bug_to_fix",
            "input": {
                "error": q["title"],
                "file": "unknown",
                "bad_code": bad_code or q["body"][:400],
            },
            "output": {
                "fix": fix_code or answer_text[:600],
                "explanation": answer_text[:300],
                "bug_class": _primary_bug_class(q["tags"]),
            },
            "tags": q["tags"][:8],
        })
        idx += 1
        if len(examples) >= limit:
            break

    logger.info("Assembled %d bug→fix pairs.", len(examples))
    return examples


# ── Output writer ──────────────────────────────────────────────────────────────


def _write_output(examples: list[dict], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "domain": "cross_domain",
        "version": "1.0",
        "generated_at": time.strftime("%Y-%m-%d"),
        "source": "stackoverflow_data_dump",
        "examples": examples,
    }
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    logger.info("Wrote %d examples to %s", len(examples), output)


# ── Entry point ────────────────────────────────────────────────────────────────


def main() -> None:
    args = _parse_args()
    logger.info(
        "so_corpus_builder starting — limit=%d, dry_run=%s, output=%s",
        args.limit, args.dry_run, args.output,
    )

    try:
        posts_path = _ensure_posts_xml(dry_run=args.dry_run, use_meta=getattr(args, "meta", False))
    except (FileNotFoundError, EnvironmentError, RuntimeError) as exc:
        logger.error("Cannot obtain Posts.xml: %s", exc)
        sys.exit(1)

    try:
        examples = _stream_questions_and_answers(posts_path, limit=args.limit)
    except Exception as exc:
        logger.error("XML parsing failed: %s", exc, exc_info=True)
        sys.exit(1)

    if not examples:
        logger.warning("No examples extracted. The dump may not contain matching posts.")
        sys.exit(0)

    _write_output(examples, args.output)
    logger.info("Done.")


if __name__ == "__main__":
    main()
