"""
Aether-One Language & Framework Auto-Detector

Purpose
-------
Provide a reusable, focused detector for:

- Programming languages present in a repo or file set
- Application frameworks (FastAPI, Django, Next.js, etc.)
- Test frameworks (pytest, unittest hints)

This is the central "what is this project?" brain that other modules
(model router, monorepo reasoning, architecture analyzer, CI agent)
can call without re-implementing heuristics.

Design
------
- Pure Python, offline, deterministic
- Safe on large repos (lightweight scanning)
- Structured output with confidences and evidence
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class DetectedLanguage:
    name: str
    file_count: int
    example_files: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DetectedFramework:
    name: str                # e.g. "FastAPI", "Django", "Next.js", "Pytest"
    category: str            # e.g. "backend", "frontend", "test"
    confidence: float        # 0.0-1.0
    evidence_files: List[str]
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DetectionResult:
    root_path: str
    languages: List[DetectedLanguage]
    frameworks: List[DetectedFramework]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


_LANGUAGE_EXTENSIONS: Dict[str, Set[str]] = {
    "python": {".py"},
    "typescript": {".ts", ".tsx"},
    "javascript": {".js", ".jsx"},
    "c": {".c", ".h"},
    "cpp": {".cc", ".cpp", ".cxx", ".hpp"},
    "rust": {".rs"},
    "go": {".go"},
    "java": {".java"},
    "shell": {".sh"},
}


def _classify_language(ext: str) -> Optional[str]:
    ext = ext.lower()
    for lang, exts in _LANGUAGE_EXTENSIONS.items():
        if ext in exts:
            return lang
    return None


def detect_file_language(path: str) -> Optional[str]:
    """
    Detect language from a single file path by extension.
    Returns language name or None if unknown.
    """
    _, ext = os.path.splitext(path)
    return _classify_language(ext)


# ---------------------------------------------------------------------------
# Filesystem and ignore rules
# ---------------------------------------------------------------------------


def _normalize_root(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _should_skip_dir(dirname: str) -> bool:
    lower = dirname.lower()
    if lower in {".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__"}:
        return True
    if lower.startswith(".pytest_cache"):
        return True
    return False


# ---------------------------------------------------------------------------
# Dependency file helpers
# ---------------------------------------------------------------------------


def _read_text_if_exists(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return None


def _detect_python_deps_from_text(text: str) -> Set[str]:
    """
    Extract coarse dependency names from requirements.txt or pyproject.toml.
    This is intentionally simple: we just look for package names containing
    key substrings (fastapi, django, flask, pytest, etc.).
    """
    deps: Set[str] = set()
    lower = text.lower()

    candidates = ["fastapi", "django", "flask", "starlette", "pytest", "unittest"]
    for c in candidates:
        if c in lower:
            deps.add(c)
    return deps


def _detect_js_deps_from_package_json(text: str) -> Set[str]:
    """
    Detect JS dependencies from a package.json text by substring;
    no full JSON parsing required for our purposes.
    """
    lower = text.lower()
    deps: Set[str] = set()
    candidates = ["next", "react", "vue", "svelte", "jest"]
    for c in candidates:
        if f'"{c}"' in lower or f"'{c}'" in lower:
            deps.add(c)
    return deps


# ---------------------------------------------------------------------------
# Framework detectors
# ---------------------------------------------------------------------------


def _detect_fastapi(root: str, python_files: Set[str]) -> Optional[DetectedFramework]:
    evidence: List[str] = []

    # 1) Look for FastAPI() usage in code
    for rel in python_files:
        full = os.path.join(root, rel)
        text = _read_text_if_exists(full)
        if not text:
            continue
        if "FastAPI(" in text:
            evidence.append(rel)
            if len(evidence) >= 3:
                break

    # 2) Look into deps
    dep_hits: Set[str] = set()
    for dep_file in ["requirements.txt", "pyproject.toml"]:
        text = _read_text_if_exists(os.path.join(root, dep_file))
        if not text:
            continue
        dep_hits |= _detect_python_deps_from_text(text)

    if "fastapi" in dep_hits and "fastapi" not in evidence:
        evidence.append("requirements.txt")

    if not evidence:
        return None

    return DetectedFramework(
        name="FastAPI",
        category="backend",
        confidence=0.9,
        evidence_files=evidence,
        notes="Detected FastAPI() usage and/or fastapi dependency.",
    )


def _detect_django(root: str, python_files: Set[str]) -> Optional[DetectedFramework]:
    evidence: List[str] = []

    # manage.py is a strong hint
    if os.path.exists(os.path.join(root, "manage.py")):
        evidence.append("manage.py")

    # django-like settings modules
    for rel in python_files:
        if "settings.py" in rel and "django" in rel.lower():
            evidence.append(rel)
            break

    # deps
    dep_hits: Set[str] = set()
    for dep_file in ["requirements.txt", "pyproject.toml"]:
        text = _read_text_if_exists(os.path.join(root, dep_file))
        if not text:
            continue
        dep_hits |= _detect_python_deps_from_text(text)

    if "django" in dep_hits and "manage.py" not in evidence:
        evidence.append("requirements.txt")

    if not evidence:
        return None

    return DetectedFramework(
        name="Django",
        category="backend",
        confidence=0.8,
        evidence_files=evidence,
        notes="Detected Django-ish structure and/or django dependency.",
    )


def _detect_pytest(root: str, python_files: Set[str]) -> Optional[DetectedFramework]:
    evidence: List[str] = []

    # tests/ folder or test_*.py files
    for rel in python_files:
        rel_unix = rel.replace("\\", "/")
        base = os.path.basename(rel_unix)
        if "tests/" in rel_unix or rel_unix.startswith("tests/"):
            evidence.append(rel_unix)
            break
        if base.startswith("test_") or base.endswith("_test.py") or base.endswith("_tests.py"):
            evidence.append(rel_unix)
            break

    # deps
    dep_hits: Set[str] = set()
    for dep_file in ["requirements.txt", "pyproject.toml"]:
        text = _read_text_if_exists(os.path.join(root, dep_file))
        if not text:
            continue
        dep_hits |= _detect_python_deps_from_text(text)

    if "pytest" in dep_hits and "requirements.txt" not in evidence:
        evidence.append("requirements.txt")

    if not evidence:
        return None

    return DetectedFramework(
        name="Pytest",
        category="test",
        confidence=0.9,
        evidence_files=evidence,
        notes="Detected pytest-style tests and/or pytest dependency.",
    )


def _detect_nextjs(root: str, js_files: Set[str]) -> Optional[DetectedFramework]:
    evidence: List[str] = []

    # next.config.* is a strong hint
    for candidate in ["next.config.js", "next.config.mjs", "next.config.ts"]:
        if os.path.exists(os.path.join(root, candidate)):
            evidence.append(candidate)
            break

    # pages/ or app/ structure with tsx/jsx
    for rel in js_files:
        rel_unix = rel.replace("\\", "/")
        if rel_unix.startswith("pages/") or rel_unix.startswith("app/"):
            _, ext = os.path.splitext(rel_unix)
            if ext in {".tsx", ".jsx"}:
                evidence.append(rel_unix)
                break

    # package.json deps
    pkg_text = _read_text_if_exists(os.path.join(root, "package.json"))
    if pkg_text:
        deps = _detect_js_deps_from_package_json(pkg_text)
        if "next" in deps and "package.json" not in evidence:
            evidence.append("package.json")

    if not evidence:
        return None

    return DetectedFramework(
        name="Next.js",
        category="frontend",
        confidence=0.85,
        evidence_files=evidence,
        notes="Detected Next.js config/pages and/or next dependency.",
    )


def _detect_react(root: str, js_files: Set[str]) -> Optional[DetectedFramework]:
    evidence: List[str] = []

    # Look for React import in a couple of files
    for rel in js_files:
        full = os.path.join(root, rel)
        text = _read_text_if_exists(full)
        if not text:
            continue
        if "from 'react'" in text or 'from "react"' in text or "React." in text:
            evidence.append(rel)
            break

    pkg_text = _read_text_if_exists(os.path.join(root, "package.json"))
    if pkg_text:
        deps = _detect_js_deps_from_package_json(pkg_text)
        if "react" in deps and "package.json" not in evidence:
            evidence.append("package.json")

    if not evidence:
        return None

    return DetectedFramework(
        name="React",
        category="frontend",
        confidence=0.8,
        evidence_files=evidence,
        notes="Detected React imports and/or react dependency.",
    )


# ---------------------------------------------------------------------------
# Main detection
# ---------------------------------------------------------------------------


def analyse_repository(root_path: str) -> DetectionResult:
    """
    Analyse a repository for languages and frameworks.

    This is the primary entrypoint other modules should call.
    """
    root_abs = _normalize_root(root_path)

    lang_counts: Dict[str, int] = {}
    lang_examples: Dict[str, List[str]] = {}

    python_files: Set[str] = set()
    js_files: Set[str] = set()

    for dirpath, dirnames, filenames in os.walk(root_abs):
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root_abs).replace("\\", "/")
            _, ext = os.path.splitext(fn)
            lang = _classify_language(ext)
            if not lang:
                continue

            lang_counts[lang] = lang_counts.get(lang, 0) + 1
            examples = lang_examples.setdefault(lang, [])
            if len(examples) < 5:
                examples.append(rel)

            if lang == "python":
                python_files.add(rel)
            if lang in {"javascript", "typescript"}:
                js_files.add(rel)

    languages: List[DetectedLanguage] = [
        DetectedLanguage(
            name=lang,
            file_count=count,
            example_files=lang_examples.get(lang, []),
        )
        for lang, count in sorted(lang_counts.items(), key=lambda kv: kv[0])
    ]

    frameworks: List[DetectedFramework] = []

    # Backend frameworks
    if python_files:
        fastapi_fw = _detect_fastapi(root_abs, python_files)
        if fastapi_fw:
            frameworks.append(fastapi_fw)

        django_fw = _detect_django(root_abs, python_files)
        if django_fw:
            frameworks.append(django_fw)

        pytest_fw = _detect_pytest(root_abs, python_files)
        if pytest_fw:
            frameworks.append(pytest_fw)

        # Generic Python library if nothing else
        if not any(f.category == "backend" for f in frameworks):
            frameworks.append(
                DetectedFramework(
                    name="PythonLibrary",
                    category="backend",
                    confidence=0.4,
                    evidence_files=sorted(list(python_files))[:5],
                    notes="Python-heavy repo; no specific backend framework detected.",
                )
            )

    # Frontend frameworks
    if js_files:
        next_fw = _detect_nextjs(root_abs, js_files)
        if next_fw:
            frameworks.append(next_fw)

        react_fw = _detect_react(root_abs, js_files)
        if react_fw:
            frameworks.append(react_fw)

        # Generic Node/JS app
        if not any(f.category == "frontend" for f in frameworks):
            frameworks.append(
                DetectedFramework(
                    name="NodeApp",
                    category="frontend",
                    confidence=0.3,
                    evidence_files=sorted(list(js_files))[:5],
                    notes="JavaScript/TypeScript files present; no specific framework detected.",
                )
            )

    return DetectionResult(
        root_path=root_abs,
        languages=languages,
        frameworks=frameworks,
    )

