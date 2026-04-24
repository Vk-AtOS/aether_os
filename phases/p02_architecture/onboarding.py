"""
Aether-One Architecture & Onboarding Analyzer

Purpose
-------
Generate a structured overview of a repository so new engineers (and agents)
can get productive quickly.

Outputs include:
- Language and framework hints
- Package / module layout
- Test & docs footprint
- Likely entrypoints (CLI, servers, main scripts)
- An "onboarding guide" with recommended reading & commands

This module is:
- Pure Python (standard library only)
- Offline and deterministic
- Safe on large repos (basic heuristics, no AST-heavy parsing)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class LanguageStats:
    """
    Count of files per language, with key examples.
    """

    language: str
    file_count: int
    example_files: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FrameworkHint:
    """
    One framework detection hint.
    """

    name: str
    confidence: float  # 0.0 - 1.0
    evidence_files: List[str]
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EntryPoint:
    """
    Likely entrypoint to run or read first.
    """

    kind: str  # e.g. "cli", "web_server", "worker", "script"
    relpath: str
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PackageInfo:
    """
    Python package / module summary.
    """

    name: str
    relpath: str
    num_modules: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OnboardingChecklistItem:
    """
    One item in the onboarding checklist.
    """

    category: str  # e.g. "READ", "RUN", "UNDERSTAND", "VERIFY"
    title: str
    description: str
    related_paths: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OnboardingGuide:
    """
    Full onboarding guide for a repo.
    """

    summary: str
    checklist: List[OnboardingChecklistItem]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ArchitectureSummary:
    """
    High-level repo architecture.
    """

    root_path: str
    language_stats: List[LanguageStats]
    frameworks: List[FrameworkHint]
    packages: List[PackageInfo]
    entrypoints: List[EntryPoint]
    test_files: List[str]
    doc_files: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RepoInsight:
    """
    Combined architecture + onboarding insight.
    """

    architecture: ArchitectureSummary
    onboarding: OnboardingGuide

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers: language detection and scanning
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
}


_DOC_EXTENSIONS = {".md", ".rst", ".adoc"}


def _classify_language_from_extension(ext: str) -> Optional[str]:
    ext = ext.lower()
    for lang, exts in _LANGUAGE_EXTENSIONS.items():
        if ext in exts:
            return lang
    return None


def _is_test_file(relpath: str) -> bool:
    name = os.path.basename(relpath)
    parts = relpath.replace("\\", "/").split("/")
    if "tests" in parts:
        return True
    if name.startswith("test_") or name.endswith("_test.py") or name.endswith("_tests.py"):
        return True
    return False


def _is_doc_file(relpath: str) -> bool:
    _, ext = os.path.splitext(relpath)
    return ext.lower() in _DOC_EXTENSIONS or "docs/" in relpath.replace("\\", "/").lower()


def _should_skip_dir(dirname: str) -> bool:
    lower = dirname.lower()
    if lower in {".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__"}:
        return True
    return False


# ---------------------------------------------------------------------------
# Framework detection
# ---------------------------------------------------------------------------


def _detect_frameworks(root_path: str, python_files: Set[str], other_files: Set[str]) -> List[FrameworkHint]:
    hints: List[FrameworkHint] = []

    def exists(*relparts: str) -> bool:
        path = os.path.join(root_path, *relparts)
        return os.path.exists(path)

    # Django
    django_evidence: List[str] = []
    if exists("manage.py"):
        django_evidence.append("manage.py")
    for rel in python_files:
        if "settings.py" in rel and "django" in rel.lower():
            django_evidence.append(rel)
    if django_evidence:
        hints.append(
            FrameworkHint(
                name="Django",
                confidence=0.8,
                evidence_files=django_evidence,
                notes="Detected manage.py and settings-like modules.",
            )
        )

    # FastAPI
    fastapi_evidence: List[str] = []
    for rel in python_files:
        if any(x in rel.lower() for x in ["api.py", "main.py", "server.py"]):
            try:
                with open(os.path.join(root_path, rel), "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                if "FastAPI(" in text:
                    fastapi_evidence.append(rel)
            except OSError:
                continue
    if fastapi_evidence:
        hints.append(
            FrameworkHint(
                name="FastAPI",
                confidence=0.9,
                evidence_files=fastapi_evidence,
                notes="Found FastAPI() usage in API/server modules.",
            )
        )

    # Next.js / React
    next_evidence: List[str] = []
    if exists("next.config.js") or exists("next.config.mjs"):
        next_evidence.append("next.config.js")
    for rel in other_files:
        if rel.startswith("pages/") or rel.startswith("app/"):
            _, ext = os.path.splitext(rel)
            if ext in {".tsx", ".jsx"}:
                next_evidence.append(rel)
    if next_evidence:
        hints.append(
            FrameworkHint(
                name="Next.js",
                confidence=0.8,
                evidence_files=next_evidence,
                notes="Detected Next.js config and page components.",
            )
        )

    # ROS2 (very lightweight heuristic)
    ros2_evidence: List[str] = []
    for rel in python_files:
        if "node.py" in rel.lower():
            ros2_evidence.append(rel)
    if exists("setup.py") or exists("package.xml"):
        if ros2_evidence:
            hints.append(
                FrameworkHint(
                    name="ROS2",
                    confidence=0.6,
                    evidence_files=ros2_evidence,
                    notes="Found node.py modules and setup/package files.",
                )
            )

    # Generic Python package
    if not hints and python_files:
        hints.append(
            FrameworkHint(
                name="PythonLibrary",
                confidence=0.4,
                evidence_files=sorted(list(python_files))[:5],
                notes="Python-heavy repo; no specific web framework detected.",
            )
        )

    return hints


# ---------------------------------------------------------------------------
# Packages & entrypoints
# ---------------------------------------------------------------------------


def _find_python_packages(root_path: str, python_files: Set[str]) -> List[PackageInfo]:
    """
    Look for directories containing __init__.py and treat them as Python packages.
    """
    seen_dirs: Set[str] = set()
    for rel in python_files:
        parts = rel.replace("\\", "/").split("/")
        if "__init__.py" in parts:
            pkg_dir = "/".join(parts[:-1])
            if pkg_dir:
                seen_dirs.add(pkg_dir)

    packages: List[PackageInfo] = []
    for pkg_dir in sorted(seen_dirs):
        pkg_name = pkg_dir.replace("/", ".")
        count = sum(1 for rel in python_files if rel.startswith(pkg_dir + "/") and rel.endswith(".py"))
        packages.append(
            PackageInfo(
                name=pkg_name,
                relpath=pkg_dir,
                num_modules=count,
            )
        )

    return packages


def _guess_entrypoints(root_path: str, python_files: Set[str]) -> List[EntryPoint]:
    """
    Guess CLI / server / script entrypoints.
    """
    entries: List[EntryPoint] = []

    def exists(rel: str) -> bool:
        return os.path.exists(os.path.join(root_path, rel))

    # Common CLIs
    for candidate in ["cli.py", "main.py"]:
        if exists(candidate):
            entries.append(
                EntryPoint(
                    kind="cli",
                    relpath=candidate,
                    description="Top-level CLI entrypoint.",
                )
            )

    # Aether-One specific CLI
    if exists("aetherone/cli.py"):
        entries.append(
            EntryPoint(
                kind="cli",
                relpath="aetherone/cli.py",
                description="Aether-One CLI orchestrator.",
            )
        )

    # Web servers (FastAPI / others)
    for rel in python_files:
        base = os.path.basename(rel)
        if base in {"api.py", "server.py", "main.py"} and "test" not in rel.lower():
            try:
                with open(os.path.join(root_path, rel), "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                if "FastAPI(" in text or "uvicorn.run" in text:
                    entries.append(
                        EntryPoint(
                            kind="web_server",
                            relpath=rel,
                            description="Likely ASGI server entrypoint.",
                        )
                    )
            except OSError:
                continue

    # Generic scripts
    if not entries:
        for rel in sorted(python_files):
            if "/scripts/" in rel or rel.startswith("scripts/"):
                entries.append(
                    EntryPoint(
                        kind="script",
                        relpath=rel,
                        description="Script under scripts/ directory.",
                    )
                )
                break

    return entries


# ---------------------------------------------------------------------------
# Onboarding guide
# ---------------------------------------------------------------------------


def _build_onboarding_guide(
    root_path: str,
    packages: List[PackageInfo],
    entrypoints: List[EntryPoint],
    frameworks: List[FrameworkHint],
    test_files: List[str],
    doc_files: List[str],
) -> OnboardingGuide:
    """
    Build a human-friendly onboarding guide from the architecture pieces.
    """
    root_name = os.path.basename(root_path.rstrip(os.sep)) or root_path
    summary = f"Onboarding guide for repository '{root_name}'."

    checklist: List[OnboardingChecklistItem] = []

    # 1) Read: architecture / core package
    core_pkg_paths = [p.relpath for p in packages if "aetherone" in p.name] or [p.relpath for p in packages]
    if core_pkg_paths:
        checklist.append(
            OnboardingChecklistItem(
                category="READ",
                title="Understand the core package layout",
                description="Start with the main application package to understand core concepts and boundaries.",
                related_paths=sorted(core_pkg_paths)[:3],
            )
        )

    # 2) Read: docs
    if doc_files:
        checklist.append(
            OnboardingChecklistItem(
                category="READ",
                title="Read high-level documentation",
                description="Review top-level docs for architecture, conventions, and workflows.",
                related_paths=sorted(doc_files)[:5],
            )
        )

    # 3) Run: entrypoints
    for ep in entrypoints:
        if ep.kind == "cli":
            checklist.append(
                OnboardingChecklistItem(
                    category="RUN",
                    title="Run the main CLI",
                    description="Start the CLI in a local environment and observe basic behavior.",
                    related_paths=[ep.relpath],
                )
            )
            break
    for ep in entrypoints:
        if ep.kind == "web_server":
            checklist.append(
                OnboardingChecklistItem(
                    category="RUN",
                    title="Run the web server",
                    description="Launch the web server and hit the health endpoints.",
                    related_paths=[ep.relpath],
                )
            )
            break

    # 4) Run: test suite
    if test_files:
        checklist.append(
            OnboardingChecklistItem(
                category="RUN",
                title="Run the test suite",
                description="Execute unit tests to validate your environment and see what is covered.",
                related_paths=sorted(test_files)[:10],
            )
        )

    # 5) Understand: frameworks
    if frameworks:
        names = [f.name for f in frameworks]
        checklist.append(
            OnboardingChecklistItem(
                category="UNDERSTAND",
                title="Review framework integration",
                description="Understand how core frameworks are wired (routing, middleware, lifecycle).",
                related_paths=[f.evidence_files[0] for f in frameworks if f.evidence_files],
            )
        )

    # 6) Verify: safety / policy (generic)
    checklist.append(
        OnboardingChecklistItem(
            category="VERIFY",
            title="Review safety, policy, and guardrails",
            description="Identify where safety policies, permissions, and approvals are enforced.",
            related_paths=[p.relpath for p in packages if "policy" in p.name.lower()] or [],
        )
    )

    return OnboardingGuide(
        summary=summary,
        checklist=checklist,
    )


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------


def analyse_repository(root_path: str) -> RepoInsight:
    """
    Analyse a repository and return a RepoInsight object.

    This is the main entrypoint for architecture + onboarding analysis.
    """
    root_abs = os.path.abspath(os.path.expanduser(root_path))

    lang_counts: Dict[str, int] = {}
    lang_examples: Dict[str, List[str]] = {}
    python_files: Set[str] = set()
    other_files: Set[str] = set()
    test_files: List[str] = []
    doc_files: List[str] = []

    for dirpath, dirnames, filenames in os.walk(root_abs):
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]

        for name in filenames:
            relpath = os.path.relpath(os.path.join(dirpath, name), root_abs)
            relpath_unix = relpath.replace("\\", "/")
            _, ext = os.path.splitext(name)

            lang = _classify_language_from_extension(ext)
            if lang:
                lang_counts[lang] = lang_counts.get(lang, 0) + 1
                lang_examples.setdefault(lang, [])
                if len(lang_examples[lang]) < 5:
                    lang_examples[lang].append(relpath_unix)
                if lang == "python":
                    python_files.add(relpath_unix)
                else:
                    other_files.add(relpath_unix)
            else:
                other_files.add(relpath_unix)

            if _is_test_file(relpath_unix):
                test_files.append(relpath_unix)
            if _is_doc_file(relpath_unix):
                doc_files.append(relpath_unix)

    language_stats: List[LanguageStats] = [
        LanguageStats(language=lang, file_count=count, example_files=lang_examples.get(lang, []))
        for lang, count in sorted(lang_counts.items(), key=lambda kv: kv[0])
    ]

    frameworks = _detect_frameworks(root_abs, python_files, other_files)
    packages = _find_python_packages(root_abs, python_files)
    entrypoints = _guess_entrypoints(root_abs, python_files)

    architecture = ArchitectureSummary(
        root_path=root_abs,
        language_stats=language_stats,
        frameworks=frameworks,
        packages=packages,
        entrypoints=entrypoints,
        test_files=sorted(test_files),
        doc_files=sorted(doc_files),
    )

    onboarding = _build_onboarding_guide(
        root_path=root_abs,
        packages=packages,
        entrypoints=entrypoints,
        frameworks=frameworks,
        test_files=architecture.test_files,
        doc_files=architecture.doc_files,
    )

    return RepoInsight(
        architecture=architecture,
        onboarding=onboarding,
    )

