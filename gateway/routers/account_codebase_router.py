"""
AetherOS — Account Codebase Router
Extracted from account_router.py.

Routes for importing and listing codebase profiles:
  POST /account/import-codebase
  GET  /account/codebase-profiles
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException
from aether_os.gateway.dependencies import get_current_user

router = APIRouter(tags=["account"])


def _current_user():
    return Depends(get_current_user)


# ── Codebase import helpers ───────────────────────────────────────────────────

_KEY_FILES = {
    "readme.md", "readme.rst", "readme.txt",
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "vite.config.ts", "vite.config.js", "next.config.js", "next.config.ts",
    "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "poetry.lock",
    "dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "go.mod", "go.sum",
    "cargo.toml", "cargo.lock",
    "pom.xml", "build.gradle", "build.gradle.kts",
    "gemfile", "gemfile.lock",
    ".env.example", ".env.sample",
    "tsconfig.json", "jsconfig.json",
    "angular.json",
    "svelte.config.js",
    "nuxt.config.ts", "nuxt.config.js",
    "prisma/schema.prisma",
    "alembic.ini",
}

_GITHUB_URL_RE = r"^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?$"


def _detect_stack(filenames: list[str]) -> dict:
    """Infer tech stack from a flat list of filenames (lowercased)."""
    names = {f.lower() for f in filenames}

    backend = ""
    if "requirements.txt" in names or "pyproject.toml" in names or "setup.py" in names:
        backend = "Python"
        # narrow down
        if any("fastapi" in f for f in names) or "fastapi" in names:
            backend = "FastAPI"
        elif "manage.py" in names:
            backend = "Django"
        elif "flask" in names:
            backend = "Flask"
    elif "go.mod" in names:
        backend = "Go"
    elif "cargo.toml" in names:
        backend = "Rust"
    elif "pom.xml" in names or "build.gradle" in names:
        backend = "Java"
    elif "gemfile" in names:
        backend = "Ruby/Rails"

    frontend = ""
    if "vite.config.ts" in names or "vite.config.js" in names:
        if "package.json" in names:
            frontend = "React/Vite"
    elif "next.config.js" in names or "next.config.ts" in names:
        frontend = "Next.js"
    elif "angular.json" in names:
        frontend = "Angular"
    elif "svelte.config.js" in names:
        frontend = "Svelte"
    elif "nuxt.config.ts" in names or "nuxt.config.js" in names:
        frontend = "Nuxt.js"
    elif "package.json" in names:
        frontend = "Node.js/JS"

    db = ""
    if "alembic.ini" in names:
        db = "PostgreSQL/SQLAlchemy"
    elif any("prisma" in f for f in names):
        db = "Prisma ORM"
    elif any("mongo" in f for f in names):
        db = "MongoDB"

    runtime = ""
    if "dockerfile" in names:
        runtime = "Docker"

    result = {}
    if backend:
        result["backend"] = backend
    if frontend:
        result["frontend"] = frontend
    if db:
        result["db"] = db
    if runtime:
        result["runtime"] = runtime
    return result


def _build_summary(repo_name: str, detected_stack: dict, key_files: list[str], top_dirs: list[str]) -> str:
    parts = [f"{repo_name} is a"]
    stack_parts = []
    if detected_stack.get("frontend"):
        stack_parts.append(detected_stack["frontend"])
    if detected_stack.get("backend"):
        stack_parts.append(detected_stack["backend"])
    if detected_stack.get("db"):
        stack_parts.append(detected_stack["db"])
    if stack_parts:
        parts.append(" + ".join(stack_parts))
    parts.append("project.")
    if top_dirs:
        parts.append(f"Top-level directories: {', '.join(top_dirs[:8])}.")
    if key_files:
        parts.append(f"Key files present: {', '.join(key_files[:10])}.")
    return " ".join(parts)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/account/import-codebase")
async def import_codebase(
    body: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Fetch a public GitHub repo's file tree, detect its stack, and store a CodebaseProfile."""
    import re
    import base64
    import httpx
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import CodebaseProfile

    repo_url: str = (body.get("repo_url") or "").strip().rstrip("/")
    branch: str = (body.get("branch") or "main").strip()
    org_id: str = user["org_id"]

    # Validate GitHub URL
    m = re.match(_GITHUB_URL_RE, repo_url)
    if not m:
        raise HTTPException(status_code=422, detail="repo_url must be a valid https://github.com/<owner>/<repo> URL")

    owner, repo = m.group(1), m.group(2)
    repo_name = f"{owner}/{repo}"

    headers: Dict[str, str] = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    gh_token = os.environ.get("GITHUB_TOKEN", "")
    if gh_token:
        headers["Authorization"] = f"Bearer {gh_token}"

    tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    readme_url = f"https://api.github.com/repos/{owner}/{repo}/readme"

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            tree_resp = await client.get(tree_url, headers=headers)
            if tree_resp.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Repository or branch '{branch}' not found on GitHub")
            if tree_resp.status_code == 403:
                raise HTTPException(status_code=503, detail="GitHub API rate limit exceeded; set GITHUB_TOKEN env var")
            tree_resp.raise_for_status()
            tree_data = tree_resp.json()

            readme_content = ""
            try:
                readme_resp = await client.get(readme_url, headers=headers)
                if readme_resp.status_code == 200:
                    encoded = readme_resp.json().get("content", "")
                    readme_content = base64.b64decode(encoded).decode("utf-8", errors="replace")[:2000]
            except Exception as exc:
                logger.debug("Failed to fetch/decode README for codebase import: %s", exc)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHub API request failed: {exc}") from exc

    # Parse the tree
    items = tree_data.get("tree", [])
    all_paths = [item["path"] for item in items if item.get("type") in ("blob", "tree")]
    blob_paths = [item["path"] for item in items if item.get("type") == "blob"]
    blob_names_lower = [p.split("/")[-1].lower() for p in blob_paths]

    # Top-level dirs
    top_dirs = sorted({
        p.split("/")[0]
        for p in all_paths
        if "/" in p
    })[:20]

    # Key files found
    found_key_files = [
        p for p in blob_paths
        if p.lower() in _KEY_FILES or p.split("/")[-1].lower() in _KEY_FILES
    ][:30]

    detected_stack = _detect_stack(blob_names_lower)
    file_tree = {
        "dirs": top_dirs,
        "key_files": found_key_files,
        "total_files": len(blob_paths),
        "truncated": tree_data.get("truncated", False),
    }

    summary = _build_summary(repo_name, detected_stack, found_key_files, top_dirs)
    if readme_content:
        # Prepend first paragraph of README for additional context
        first_para = readme_content.split("\n\n")[0].strip()[:400]
        if first_para:
            summary = f"{summary} README: {first_para}"

    sf = get_session_factory()
    async with sf() as session:
        profile = CodebaseProfile(
            org_id=org_id,
            repo_url=repo_url,
            repo_name=repo_name,
            detected_stack=detected_stack,
            file_tree=file_tree,
            summary=summary,
        )
        session.add(profile)
        await session.commit()
        await session.refresh(profile)

    return {
        "id": profile.id,
        "repo_url": profile.repo_url,
        "repo_name": profile.repo_name,
        "detected_stack": profile.detected_stack,
        "file_tree": profile.file_tree,
        "summary": profile.summary,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
    }


@router.get("/account/codebase-profiles")
async def list_codebase_profiles(
    user: Dict[str, Any] = _current_user(),
) -> List[Dict[str, Any]]:
    """Return all imported codebase profiles for the current org."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import CodebaseProfile
    from sqlalchemy import select

    org_id = user["org_id"]
    sf = get_session_factory()
    async with sf() as session:
        rows = (await session.execute(
            select(CodebaseProfile)
            .where(CodebaseProfile.org_id == org_id)
            .order_by(CodebaseProfile.created_at.desc())
            .limit(50)
        )).scalars().all()

    return [
        {
            "id": p.id,
            "repo_url": p.repo_url,
            "repo_name": p.repo_name,
            "detected_stack": p.detected_stack,
            "file_tree": p.file_tree,
            "summary": p.summary,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in rows
    ]
