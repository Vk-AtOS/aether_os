"""
AetherOS — Account Router
GET /account/usage
GET /account/storage
GET /account/projects
GET /account/projects/search
GET /account/data-export
DELETE /account
GET /account/preferences
PUT /account/preferences
POST /account/settings
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Response

router = APIRouter(tags=["account"])


def _current_user():
    from aether_os.gateway.api import get_current_user
    return Depends(get_current_user)


@router.get("/account/usage")
async def get_usage(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Get current usage and limits for the organisation."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation
    from sqlalchemy import select

    org_id = user.get("org_id")
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(Organisation).where(Organisation.id == org_id)
        result = await session.execute(stmt)
        org = result.scalar_one_or_none()
        if not org:
            raise HTTPException(status_code=404, detail="Organisation not found")

        return {
            "org_name": org.name,
            "org_slug": org.slug,
            "plan": org.plan,
            "runs_used": org.trial_runs_used,
            "runs_limit": org.trial_runs_limit if org.plan == "trial" else None,
            "runs_remaining": max(0, org.trial_runs_limit - org.trial_runs_used) if org.plan == "trial" else None,
        }


@router.get("/account/storage")
async def get_account_storage(user: Dict[str, Any] = _current_user()):
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation
    from sqlalchemy import select
    async with get_session_factory()() as session:
        stmt = select(Organisation).where(Organisation.id == user["org_id"])
        org = (await session.execute(stmt)).scalar_one_or_none()
        if not org:
            raise HTTPException(status_code=404)
        limit = -1
        if org.plan == "trial": limit = 500
        elif org.plan == "pro": limit = 10000
        return {"used_mb": org.storage_used_mb, "limit_mb": limit, "percent_used": (org.storage_used_mb / limit * 100) if limit > 0 else 0, "plan": org.plan}


@router.get("/account/projects")
async def list_projects(user: Dict[str, Any] = _current_user()) -> List[Dict[str, Any]]:
    """List all generated projects for the org."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Run
    from sqlalchemy import select, func

    org_id = user["org_id"]
    sf = get_session_factory()
    async with sf() as session:
        rows = (await session.execute(
            select(
                Run.project_name,
                Run.domain,
                Run.status,
                func.count().label("run_count"),
                func.max(Run.started_at).label("last_run_at"),
                func.max(Run.id).label("run_id"),
            )
            .where(Run.org_id == org_id)
            .group_by(Run.project_name, Run.domain, Run.status)
            .order_by(func.max(Run.started_at).desc())
        )).all()
    return [
        {
            "project_name": r.project_name,
            "domain": r.domain,
            "run_count": r.run_count,
            "last_run_at": r.last_run_at,
            "status": r.status,
            "run_id": r.run_id,
        }
        for r in rows
    ]


@router.get("/account/projects/search")
async def search_projects(q: str, user: Dict[str, Any] = _current_user()) -> List[Dict[str, Any]]:
    """Search projects by name or requirement text."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Run
    from sqlalchemy import select, func, or_

    org_id = user["org_id"]
    pattern = f"%{q}%"
    sf = get_session_factory()
    async with sf() as session:
        rows = (await session.execute(
            select(
                Run.project_name,
                Run.domain,
                Run.status,
                func.count().label("run_count"),
                func.max(Run.started_at).label("last_run_at"),
                func.max(Run.id).label("run_id"),
            )
            .where(
                Run.org_id == org_id,
                or_(
                    Run.project_name.ilike(pattern),
                    Run.command.ilike(pattern),
                    Run.raw_input.ilike(pattern) if hasattr(Run, "raw_input") else Run.command.ilike(pattern),
                )
            )
            .group_by(Run.project_name, Run.domain, Run.status)
            .order_by(func.max(Run.started_at).desc())
            .limit(50)
        )).all()
    return [
        {
            "project_name": r.project_name or f"run-{r.run_id[:8]}",
            "domain": r.domain or "general",
            "run_count": r.run_count,
            "last_run_at": r.last_run_at,
            "status": r.status,
            "run_id": r.run_id,
        }
        for r in rows
    ]


@router.get("/account/data-export")
async def data_export(user: Dict[str, Any] = _current_user()):
    """GDPR portability: return all user data as a downloadable JSON file."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User, Run
    from aether_os.core.audit.ledger import get_ledger
    from sqlalchemy import select
    from fastapi.responses import StreamingResponse
    import json as _json

    user_id = user.get("user_id", "")
    org_id = user.get("org_id", "")
    sf = get_session_factory()
    async with sf() as session:
        db_user = await session.get(User, user_id)
        runs = (await session.execute(
            select(Run).where(Run.org_id == org_id)
            .order_by(Run.started_at.desc()).limit(500)
        )).scalars().all()

    audit = await get_ledger().async_get_audit_logs(org_id=org_id, page=1, limit=500)
    export = {
        "export_version": "1.0",
        "exported_at": time.time(),
        "user": {
            "id": user_id,
            "email": db_user.email if db_user else None,
            "role": db_user.role if db_user else None,
            "created_at": str(db_user.created_at) if db_user else None,
            "consent_at": str(db_user.consent_at) if db_user and db_user.consent_at else None,
        },
        "runs": [
            {"id": r.id, "project_name": r.project_name, "status": r.status,
             "domain": r.domain, "started_at": r.started_at, "cost": r.cost}
            for r in runs
        ],
        "audit_logs": audit.get("logs", []),
    }
    payload = _json.dumps(export, indent=2, default=str).encode()
    return StreamingResponse(
        iter([payload]),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="aetheros-data-export.json"'},
    )


@router.delete("/account")
async def delete_account(user: Dict[str, Any] = _current_user()) -> Dict[str, str]:
    """GDPR erasure: anonymise and soft-delete the calling user's account."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User, APIKey
    from aether_os.core.audit.ledger import get_ledger
    from sqlalchemy import update as _saup
    from datetime import datetime as _dt

    user_id = user.get("user_id", "")
    org_id = user.get("org_id", "")
    sf = get_session_factory()
    async with sf() as session:
        db_user = await session.get(User, user_id)
        if not db_user or db_user.org_id != org_id:
            raise HTTPException(status_code=404, detail="User not found")
        db_user.email = f"deleted_{user_id[:8]}@deleted.invalid"
        db_user.password_hash = "DELETED"
        db_user.is_active = False
        db_user.deleted_at = _dt.utcnow()
        db_user.user_preferences = None
        await session.execute(_saup(APIKey).where(APIKey.org_id == org_id).values(is_active=False))
        await session.commit()

    jti = user.get("jti")
    exp = user.get("exp", 0)
    if jti:
        try:
            from aether_os.core.pipeline_state import get_redis
            r = await get_redis()
            if r:
                ttl = max(1, int(exp - time.time()))
                await r.setex(f"jwt:blacklist:{jti}", ttl, "1")
        except Exception:
            pass

    await get_ledger().async_log_audit_event(
        org_id=org_id, user_id=user_id, action="account.deleted",
        resource_type="user", resource_id=user_id, metadata={}, ip_address="self",
    )
    return {"message": "Account deleted"}


@router.get("/account/preferences")
async def get_preferences(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Get user preferences."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User
    from sqlalchemy import select
    import json

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(User).where(User.id == user["user_id"])
        result = await session.execute(stmt)
        u = result.scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404)
        return json.loads(u.user_preferences) if u.user_preferences else dict(_DEFAULT_PREFERENCES)


_DEFAULT_PREFERENCES = {
    "default_tab_on_run_complete": "artifacts",
    "pinned_phases": [],
    "collapsed_phases": [],
    "decision_notification_style": "panel",
    "live_feed_visible_by_default": True,
    "default_domain": "general",
    "default_start_mode": "single",
    "dashboard_theme": "default",
    "sidebar_collapsed": False,
    "compact_phase_list": False,
    "show_confidence_scores": True,
    "workspace_name": "My Workspace",
}


@router.put("/account/preferences")
async def update_preferences(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Update user preferences."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import User
    from sqlalchemy import select, update
    import json

    # Fetch existing preferences and merge
    session_factory = get_session_factory()
    async with session_factory() as session:
        u = (await session.execute(select(User).where(User.id == user["user_id"]))).scalar_one_or_none()
        existing = json.loads(u.user_preferences) if u and u.user_preferences else dict(_DEFAULT_PREFERENCES)
        existing.update(req)
        stmt = update(User).where(User.id == user["user_id"]).values(user_preferences=json.dumps(existing))
        await session.execute(stmt)
        await session.commit()
    return existing


@router.post("/account/settings")
async def update_settings(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Update account settings (e.g. decision_mode, autonomous_mode)."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation
    from sqlalchemy import update

    # Allowlist: only non-privileged fields may be updated by org members (FIX-006)
    _ALLOWED = {"decision_mode", "autonomous_mode", "notification_prefs", "org_name", "data_region"}
    payload = {k: v for k, v in req.items() if k in _ALLOWED}
    if not payload:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = update(Organisation).where(Organisation.id == user["org_id"]).values(payload)
        await session.execute(stmt)
        await session.commit()
        return {"status": "ok", "updated": list(payload.keys())}


@router.get("/account/settings")
async def get_org_settings(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return org-level settings (autonomous_mode, data_region, etc.)."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation
    session_factory = get_session_factory()
    async with session_factory() as session:
        org = await session.get(Organisation, user["org_id"])
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    return {
        "autonomous_mode": org.autonomous_mode,
        "data_region": org.data_region,
        "plan": org.plan,
        "name": org.name,
    }


@router.delete("/account/org", status_code=204, response_model=None)
async def delete_organisation(
    user: Dict[str, Any] = _current_user(),
) -> None:
    """Permanently delete the current organisation and all its data (owner only)."""
    if user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Only org owners can delete the organisation")
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation
    session_factory = get_session_factory()
    async with session_factory() as session:
        org = await session.get(Organisation, user["org_id"])
        if not org:
            raise HTTPException(status_code=404, detail="Organisation not found")
        await session.delete(org)
        await session.commit()


# ── Codebase import ───────────────────────────────────────────────────────────

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


@router.post("/account/import-codebase")
async def import_codebase(
    body: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Fetch a public GitHub repo's file tree, detect its stack, and store a CodebaseProfile."""
    import re
    import os
    import base64
    import httpx
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import CodebaseProfile
    from sqlalchemy import select

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
            except Exception:
                pass
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
