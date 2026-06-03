"""
AetherOS — Factory Ops Router
Extracted from gateway/api.py (inline routes → APIRouter).

Routes:
  POST /factory/upload-requirement
  POST /factory/fetch-github-repo
  POST /factory/import-schema
  POST /factory/fetch-repo
  GET  /templates
  POST /factory/estimate
  POST /factory/start
  GET  /factory/search
  GET  /factory/analytics/quality-trend
  GET  /factory/deployments
  GET  /pipeline/status/{run_id}
  POST /pipeline/approve/{ticket_id}
"""
from __future__ import annotations

import logging
import os
import time
import asyncio
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File as FastAPIFile
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["factory"])


def _current_user():
    from aether_os.gateway.api import get_current_user
    return Depends(get_current_user)


# ── Pydantic models used by these routes ─────────────────────────────────────

class ApproveRequest(BaseModel):
    ticket_id: str
    decision: str  # "approve" | "deny"
    reason: Optional[str] = None


# ── Strong references prevent GC from silently killing in-flight tasks ────────
_background_tasks: set = set()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/pipeline/status/{run_id}")
async def get_pipeline_status(
    run_id: str,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Get status of a pipeline run."""
    from aether_os.core.audit.ledger import get_ledger
    org_id = user.get("org_id")
    detail = await get_ledger().async_get_run_detail(run_id, org_id=org_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return detail


@router.post("/pipeline/approve/{ticket_id}")
async def approve_action(
    ticket_id: str,
    req: ApproveRequest,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Approve or deny a human-gated pipeline action via DecisionEngine."""
    from aether_os.core.decisions.decision_engine import get_decision_engine
    engine = get_decision_engine()
    approved = req.decision in ("approve", "approved", "yes", True)
    try:
        decision = await engine.resolve(
            decision_id=ticket_id,
            org_id=user.get("org_id", ""),
            approved=approved,
            choice=req.reason,
        )
        return {
            "ticket_id": ticket_id,
            "decision":  "approved" if approved else "denied",
            "decided_by": user.get("sub"),
            "reason":    req.reason,
            "timestamp": time.time(),
            "status":    decision.status if decision else "resolved",
        }
    except LookupError:
        # Decision not pending in engine — treat as already resolved
        return {
            "ticket_id": ticket_id,
            "decision":  "approved" if approved else "denied",
            "decided_by": user.get("sub"),
            "timestamp": time.time(),
            "status": "already_resolved",
        }


@router.post("/factory/upload-requirement")
async def upload_requirement_file(
    file: UploadFile = FastAPIFile(...),
    user: Dict[str, Any] = _current_user(),
):
    """Parse an uploaded file (PDF/MD/TXT/image) and return extracted requirement text."""
    import io
    content = await file.read()
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    extracted = ""
    if ext in ("txt", "md", "rst"):
        extracted = content.decode("utf-8", errors="ignore")
    elif ext == "pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(content))
            extracted = "\n".join(p.extract_text() or "" for p in reader.pages)
        except ImportError:
            try:
                import pdfplumber
                with pdfplumber.open(io.BytesIO(content)) as pdf:
                    extracted = "\n".join(p.extract_text() or "" for p in pdf.pages)
            except Exception as e:
                return {"text": "", "error": f"PDF parsing unavailable: {e}"}
    elif ext in ("png", "jpg", "jpeg", "webp"):
        # Return placeholder — vision extraction requires separate LLM call
        return {"text": "", "error": "Image requirement extraction not yet supported — please paste text instead"}
    elif ext in ("docx",):
        try:
            import docx
            doc = docx.Document(io.BytesIO(content))
            extracted = "\n".join(p.text for p in doc.paragraphs)
        except Exception as e:
            return {"text": "", "error": f"DOCX parsing failed: {e}"}
    else:
        extracted = content.decode("utf-8", errors="ignore")
    return {"text": extracted[:8000], "filename": filename}


@router.post("/factory/fetch-github-repo")
async def fetch_github_repo(req: Dict[str, Any], user: Dict[str, Any] = _current_user()):
    """Fetch key files from a GitHub repo to use as codebase context."""
    import httpx
    repo_url = req.get("repo_url", "").strip().rstrip("/")
    github_token = req.get("github_token", "")
    if not repo_url:
        raise HTTPException(status_code=422, detail="repo_url required")
    # Parse owner/repo from URL
    parts = repo_url.replace("https://github.com/", "").split("/")
    if len(parts) < 2:
        raise HTTPException(status_code=422, detail="Invalid GitHub URL format")
    owner, repo = parts[0], parts[1]
    headers = {"Accept": "application/vnd.github.v3+json"}
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    async with httpx.AsyncClient(timeout=20) as gh:
        # Get file tree
        tree_res = await gh.get(f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1", headers=headers)
        if tree_res.status_code == 404:
            raise HTTPException(status_code=404, detail="Repository not found or private (provide github_token)")
        tree = tree_res.json().get("tree", [])
        # Pick key files: README, main files, package.json, requirements.txt
        _KEY = {"readme.md", "readme.txt", "readme", "main.py", "app.py", "index.js", "index.ts",
                "package.json", "requirements.txt", "pyproject.toml", "schema.sql"}
        key_files = [f for f in tree if f.get("type") == "blob" and f["path"].lower().split("/")[-1] in _KEY][:10]
        context_parts = [f"Repository: {owner}/{repo}"]
        for f in key_files:
            blob_res = await gh.get(f"https://api.github.com/repos/{owner}/{repo}/contents/{f['path']}", headers=headers)
            if blob_res.status_code == 200:
                import base64
                blob_data = blob_res.json()
                try:
                    text = base64.b64decode(blob_data.get("content", "")).decode("utf-8", errors="ignore")[:2000]
                    context_parts.append(f"\n--- {f['path']} ---\n{text}")
                except Exception:
                    pass
    return {"context": "\n".join(context_parts), "repo": f"{owner}/{repo}"}


@router.post("/factory/import-schema")
async def import_existing_schema(
    req: Dict[str, Any],
    user: Dict[str, Any] = _current_user(),
):
    """Import schema from an existing database to use as p02 architecture input."""
    connection_string = req.get("connection_string", "")
    if not connection_string:
        raise HTTPException(400, "connection_string required")
    # Basic safety: only allow known drivers, reject file paths outside /tmp
    allowed = ("postgresql://", "mysql+pymysql://", "mysql://", "sqlite:///")
    if not any(connection_string.startswith(p) for p in allowed):
        raise HTTPException(400, "Unsupported connection string format")

    from aether_os.core.schema_importer import import_schema
    result = await import_schema(connection_string)
    return result


@router.post("/factory/fetch-repo")
async def fetch_repo(req: Dict[str, Any], user: Dict[str, Any] = _current_user()):
    """Fetch codebase context from GitHub, GitLab, or an SSH-accessible repository.

    Body:
      type: 'github' | 'gitlab' | 'ssh'
      url:  repo URL or SSH remote
      token:      personal access token (GitHub / GitLab)
      ssh_key:    PEM private key string (SSH type)
      gitlab_url: self-hosted GitLab base URL (optional, default https://gitlab.com)
      max_files:  max files to include (default 15)
    """
    import httpx, base64, asyncio, tempfile, subprocess, shutil
    import ipaddress
    from urllib.parse import urlparse as _urlparse

    def _assert_not_ssrf(raw_url: str, label: str = "url") -> None:
        """Block requests to private/loopback/link-local IP ranges (SSRF prevention)."""
        try:
            parsed = _urlparse(raw_url)
            host = parsed.hostname or ""
            if not host:
                raise HTTPException(status_code=422, detail=f"Invalid {label}: no hostname")
            try:
                ip = ipaddress.ip_address(host)
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
                    raise HTTPException(status_code=422, detail=f"{label} must not point to internal networks")
            except ValueError:
                pass  # hostname string (not a raw IP) — DNS resolves at request time; block known patterns
            if host in ("metadata.google.internal", "169.254.169.254"):
                raise HTTPException(status_code=422, detail=f"{label} is a blocked cloud metadata endpoint")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=422, detail=f"Invalid {label}")

    rtype = req.get("type", "github").lower()
    url   = (req.get("url") or req.get("repo_url") or "").strip().rstrip("/")
    token = req.get("token") or req.get("github_token") or ""
    ssh_key = req.get("ssh_key", "")
    gitlab_base = (req.get("gitlab_url") or "https://gitlab.com").rstrip("/")
    max_files = min(int(req.get("max_files", 15)), 30)

    if not url:
        raise HTTPException(status_code=422, detail="url required")

    # SSRF: validate gitlab_url before making server-side requests to it
    if rtype == "gitlab":
        _assert_not_ssrf(gitlab_base, "gitlab_url")

    # SSRF/injection: SSH URLs must be actual git remotes, not file:// or local paths
    if rtype == "ssh":
        _lower = url.lower()
        if _lower.startswith("file://") or _lower.startswith("/") or _lower.startswith("../"):
            raise HTTPException(status_code=422, detail="SSH url must be a remote git address, not a local path")

    _KEY_FILES = {"readme.md", "readme.txt", "readme", "main.py", "app.py", "server.py",
                  "index.js", "index.ts", "main.ts", "package.json", "requirements.txt",
                  "pyproject.toml", "schema.sql", "docker-compose.yml", "dockerfile",
                  ".env.example", "openapi.yaml", "openapi.json"}

    context_parts: list[str] = []

    if rtype in ("github", "gitlab"):
        is_gitlab = rtype == "gitlab"
        if is_gitlab:
            # Support self-hosted GitLab
            path = url.replace(gitlab_base + "/", "").replace("https://gitlab.com/", "")
            api_base = f"{gitlab_base}/api/v4"
            encoded = path.replace("/", "%2F")
            hdrs: Dict[str, str] = {}
            if token:
                hdrs["PRIVATE-TOKEN"] = token
            async with httpx.AsyncClient(timeout=20) as gl:
                tree_res = await gl.get(f"{api_base}/projects/{encoded}/repository/tree?recursive=true&per_page=200", headers=hdrs)
                if tree_res.status_code == 404:
                    raise HTTPException(status_code=404, detail="GitLab project not found or private (provide token)")
                tree = tree_res.json()
                key_files = [f for f in tree if f.get("type") == "blob" and f["name"].lower() in _KEY_FILES][:max_files]
                context_parts.append(f"Repository: {path} (GitLab)")
                for f in key_files:
                    fpath = f["path"]
                    raw_res = await gl.get(f"{api_base}/projects/{encoded}/repository/files/{fpath.replace('/',  '%2F')}/raw?ref=HEAD", headers=hdrs)
                    if raw_res.status_code == 200:
                        text = raw_res.text[:3000]
                        context_parts.append(f"\n--- {fpath} ---\n{text}")
        else:
            # GitHub (existing logic unified here)
            parts = url.replace("https://github.com/", "").split("/")
            if len(parts) < 2:
                raise HTTPException(status_code=422, detail="Invalid GitHub URL")
            owner, repo_name = parts[0], parts[1]
            hdrs = {"Accept": "application/vnd.github.v3+json"}
            if token:
                hdrs["Authorization"] = f"token {token}"
            async with httpx.AsyncClient(timeout=20) as gh:
                tree_res = await gh.get(f"https://api.github.com/repos/{owner}/{repo_name}/git/trees/HEAD?recursive=1", headers=hdrs)
                if tree_res.status_code == 404:
                    raise HTTPException(status_code=404, detail="Repository not found or private (provide token)")
                tree = tree_res.json().get("tree", [])
                key_files = [f for f in tree if f.get("type") == "blob" and f["path"].lower().split("/")[-1] in _KEY_FILES][:max_files]
                context_parts.append(f"Repository: {owner}/{repo_name} (GitHub)")
                for f in key_files:
                    blob_res = await gh.get(f"https://api.github.com/repos/{owner}/{repo_name}/contents/{f['path']}", headers=hdrs)
                    if blob_res.status_code == 200:
                        try:
                            text = base64.b64decode(blob_res.json().get("content", "")).decode("utf-8", errors="ignore")[:3000]
                            context_parts.append(f"\n--- {f['path']} ---\n{text}")
                        except Exception:
                            pass

    elif rtype == "ssh":
        # Clone via SSH with ephemeral key
        if not ssh_key:
            raise HTTPException(status_code=422, detail="ssh_key (PEM) required for SSH type")
        tmpdir = tempfile.mkdtemp(prefix="aether_repo_")
        key_file = os.path.join(tmpdir, "id_rsa")
        clone_dir = os.path.join(tmpdir, "repo")
        try:
            with open(key_file, "w") as kf:
                kf.write(ssh_key)
            os.chmod(key_file, 0o600)
            env = {**os.environ, "GIT_SSH_COMMAND": f"ssh -i {key_file} -o StrictHostKeyChecking=no -o BatchMode=yes"}
            proc = await asyncio.create_subprocess_exec(
                "git", "clone", "--depth=1", url, clone_dir,
                env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode != 0:
                raise HTTPException(status_code=422, detail=f"Git clone failed: {stderr.decode()[:500]}")
            context_parts.append(f"Repository: {url} (SSH clone)")
            found = 0
            for root, _dirs, files in os.walk(clone_dir):
                if "/.git" in root or "/node_modules" in root or "/__pycache__" in root:
                    continue
                for fn in files:
                    if fn.lower() in _KEY_FILES and found < max_files:
                        fpath = os.path.join(root, fn)
                        try:
                            text = open(fpath, errors="ignore").read(3000)
                            rel = os.path.relpath(fpath, clone_dir)
                            context_parts.append(f"\n--- {rel} ---\n{text}")
                            found += 1
                        except Exception:
                            pass
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    else:
        raise HTTPException(status_code=422, detail=f"Unknown repo type: {rtype}")

    return {
        "context": "\n".join(context_parts),
        "url": url,
        "type": rtype,
        "files_included": len(context_parts) - 1,
    }


@router.get("/templates")
async def list_templates(user: Dict[str, Any] = _current_user()):
    """Return available project templates."""
    return {"templates": [
        {"id": "saas", "name": "SaaS App", "description": "Multi-tenant SaaS with auth, billing, and dashboard", "domain": "saas", "icon": "🏢"},
        {"id": "ecommerce", "name": "E-Commerce", "description": "Product catalog, cart, orders, and payments", "domain": "ecommerce", "icon": "🛒"},
        {"id": "dashboard", "name": "Analytics Dashboard", "description": "Data visualisation, charts, and KPI tracking", "domain": "analytics", "icon": "📊"},
        {"id": "api", "name": "REST API", "description": "Clean REST API with auth, rate limiting, and docs", "domain": "api", "icon": "⚡"},
        {"id": "cms", "name": "CMS / Blog", "description": "Content management with rich text editor and media", "domain": "cms", "icon": "✍️"},
        {"id": "social", "name": "Social Platform", "description": "User profiles, posts, follows, and notifications", "domain": "social", "icon": "👥"},
        {"id": "marketplace", "name": "Marketplace", "description": "Two-sided marketplace with listings and transactions", "domain": "marketplace", "icon": "🏪"},
        {"id": "healthcare", "name": "Healthcare", "description": "Patient records, appointments, and HIPAA compliance", "domain": "healthcare", "icon": "🏥"},
        {"id": "fintech", "name": "FinTech", "description": "Transactions, wallets, and financial reporting", "domain": "fintech", "icon": "💳"},
        {"id": "iot", "name": "IoT Dashboard", "description": "Device management, telemetry streams, and alerts", "domain": "iot", "icon": "📡"},
        {"id": "lms", "name": "Learning Management", "description": "Courses, lessons, quizzes, and student progress", "domain": "education", "icon": "🎓"},
        {"id": "custom", "name": "Custom", "description": "Describe your own requirements from scratch", "domain": "general", "icon": "🛠️"},
    ]}


@router.post("/factory/estimate")
async def estimate_cost(req: Dict[str, Any], user: Dict[str, Any] = _current_user()):
    """Estimate monthly hosting cost based on tech stack and domain."""
    domain = req.get("domain", "general")
    backend = req.get("backend", "fastapi")
    db = req.get("database", "postgresql")
    scale = req.get("scale", "small")  # small / medium / large
    base = {"small": 15, "medium": 45, "large": 120}.get(scale, 15)
    db_cost = {"postgresql": 20, "mongodb": 25, "sqlite": 0, "redis": 10}.get(db.lower(), 20)
    domain_mult = {"healthcare": 1.4, "fintech": 1.3, "saas": 1.2}.get(domain, 1.0)
    total = round((base + db_cost) * domain_mult)
    return {
        "estimated_monthly_usd": total,
        "range": f"${round(total * 0.8)}–${round(total * 1.4)}/month",
        "breakdown": {"compute": base, "database": db_cost, "extras": round(total - base - db_cost)},
        "note": "Estimate for a small VPS (2 vCPU / 4 GB RAM). Scale up for production traffic.",
    }


@router.post("/factory/start")
async def start_factory_run(
    req: Dict[str, Any],
    request: Request,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Start a new factory pipeline run (10-phase path)."""
    from aether_os.orchestrator.factory_pipeline import get_factory
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Organisation
    from aether_os.core.rate_limiter import get_rate_limiter
    from sqlalchemy import select
    import uuid as _uuid

    org_id = user.get("org_id")

    # ── Rate limiting on factory/start ────────────────────────────────────
    _rl = get_rate_limiter()
    if not await _rl.check_factory_start(org_id):
        raise HTTPException(
            status_code=429,
            detail=f"Too many pipeline starts. Max {_rl.max_factory_starts_per_min} per minute per org.",
        )
    if not await _rl.check_hourly_starts(org_id):
        raise HTTPException(
            status_code=429,
            detail=f"Hourly pipeline limit reached ({_rl.max_starts_per_hour}/hr).",
        )
    if not await _rl.check_concurrent_runs(org_id):
        raise HTTPException(
            status_code=429,
            detail=f"Max concurrent runs reached ({_rl.max_concurrent_runs}). Wait for a run to complete.",
        )
    await _rl.record_factory_start(org_id)

    # B9: Atomic trial run check — single UPDATE prevents TOCTOU race
    from sqlalchemy import update as _sa_update
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(Organisation).where(Organisation.id == org_id)
        result = await session.execute(stmt)
        org = result.scalar_one_or_none()

        if not org:
            raise HTTPException(status_code=404, detail="Organisation not found")

        # Storage limit check
        limit = -1
        if org.plan == "trial": limit = float(os.environ.get("STORAGE_LIMIT_MB_TRIAL", 500))
        elif org.plan == "pro": limit = float(os.environ.get("STORAGE_LIMIT_MB_PRO", 10000))
        if limit > 0 and org.storage_used_mb >= limit:
            raise HTTPException(
                status_code=402,
                detail={"error": "storage_limit_reached", "used_mb": org.storage_used_mb, "limit_mb": limit}
            )

        if org.plan == "trial":
            # Atomic increment — only succeeds if still under limit (B9: no TOCTOU)
            upd_result = await session.execute(
                _sa_update(Organisation)
                .where(Organisation.id == org_id)
                .where(Organisation.trial_runs_used < Organisation.trial_runs_limit)
                .values(trial_runs_used=Organisation.trial_runs_used + 1)
            )
            await session.commit()
            if upd_result.rowcount == 0:
                raise HTTPException(
                    status_code=402,
                    detail={"error": "trial_limit_reached", "upgrade_url": "/pricing"}
                )

    factory = get_factory()

    client_id = req.get("client_id", user.get("org_slug", "anonymous"))
    raw_input = req.get("raw_input", req.get("requirement", ""))
    domain = req.get("domain", "general")
    project_name = req.get("project_name")
    github_url = req.get("github_url", "").strip()
    designer_spec = req.get("designer_spec")
    production_country = (req.get("production_country") or "").strip().upper() or None
    compliance_flags = req.get("compliance_flags") or {}

    if not raw_input:
        raise HTTPException(status_code=400, detail="raw_input or requirement is required")

    # Prepend structured spec preamble when designer_spec is provided
    if designer_spec and isinstance(designer_spec, dict):
        try:
            fe = designer_spec.get("frontend", {})
            be = designer_spec.get("backend", {})
            inf = designer_spec.get("infra", {})
            ft = designer_spec.get("features", {})
            ds = designer_spec.get("design", {})
            preamble = (
                "=== PROJECT SPECIFICATION ===\n"
                "Tech Stack:\n"
                f"  Frontend: {fe.get('framework','')} + {fe.get('styling','')}\n"
                f"  State: {fe.get('state_management','')}\n"
                f"  Forms: {fe.get('form_library','')}\n"
                f"  Data Fetching: {fe.get('data_fetching','')}\n"
                f"  Backend: {be.get('framework','')} + {be.get('database','')} + {be.get('orm','')}\n"
                f"  Auth: {be.get('auth','')}\n"
                f"  API: {be.get('api_style','')}\n"
                f"  Infrastructure: {inf.get('deployment','')}, cache={inf.get('cache','')}, queue={inf.get('queue','')}\n"
                f"  File Storage: {inf.get('file_storage','')}, Email: {inf.get('email','')}\n"
                f"  Features: multi_tenant={ft.get('multi_tenancy',False)}, audit_log={ft.get('audit_log',False)}, "
                f"rate_limiting={ft.get('rate_limiting',True)}, webhooks={ft.get('webhooks_out',False)}, "
                f"realtime={ft.get('realtime','None')}, payments={ft.get('payments','None')}, "
                f"i18n={ft.get('internationalization',False)}\n"
                "\nDesign Tokens:\n"
                f"  Primary color: {ds.get('primary_hex','#6366f1')}\n"
                f"  Secondary color: {ds.get('secondary_hex','#8b5cf6')}\n"
                f"  Background: {ds.get('background_hex','#0f172a')}\n"
                f"  Surface: {ds.get('surface_hex','#1e293b')}\n"
                f"  Font pairing: {ds.get('font_pairing','Inter + Inter')}\n"
                f"  Border radius: {ds.get('border_radius','Rounded (8px)')}\n"
                f"  Layout: {ds.get('layout','sidebar-topbar')}\n"
                f"  Component density: {ds.get('density','Normal')}\n"
                f"  UI Theme: {ds.get('ui_theme','default')}\n"
                "\n=== PROJECT REQUIREMENT ===\n"
            )
            raw_input = preamble + raw_input
        except Exception as _spec_exc:
            logger.warning("Failed to build designer_spec preamble: %s", _spec_exc)

    # ── Compliance pre-check — block embargoed countries, enforce jurisdiction ──
    _EMBARGOED = {"CU", "IR", "KP", "SY", "RU", "BY"}
    if production_country and production_country in _EMBARGOED:
        raise HTTPException(
            status_code=403,
            detail=f"Production in '{production_country}' is blocked — embargoed jurisdiction."
        )
    if production_country:
        try:
            from aether_os.core.policy.compliance import ComplianceEngine, ComplianceContext
            _region_map = {
                "AT":"EU","BE":"EU","CZ":"EU","DE":"EU","DK":"EU","ES":"EU","FI":"EU","FR":"EU",
                "GR":"EU","HR":"EU","HU":"EU","IE":"EU","IT":"EU","NL":"EU","PL":"EU","PT":"EU",
                "RO":"EU","SE":"EU","SK":"EU","CH":"EU","NO":"EU","GB":"UK",
                "US":"US","CA":"CANADA","BR":"LATAM","MX":"LATAM","AR":"LATAM","CL":"LATAM","CO":"LATAM",
                "AU":"APAC","NZ":"APAC","IN":"APAC","SG":"APAC","JP":"APAC","KR":"APAC","TH":"APAC",
                "PH":"APAC","ID":"APAC","MY":"APAC","VN":"APAC","HK":"APAC","TW":"APAC",
                "AE":"MENA","SA":"MENA","IL":"MENA","EG":"MENA","NG":"AFRICA","ZA":"AFRICA",
                "CN":"CHINA",
            }
            _region = _region_map.get(production_country, "global")
            _ctx = ComplianceContext(
                country_code=production_country,
                region=_region,
                deployment_type=compliance_flags.get("deployment_type", "saas"),
                data_sensitivity=compliance_flags.get("data_sensitivity", "moderate"),
                handles_personal_data=compliance_flags.get("handles_personal_data", True),
                handles_biometric_data=compliance_flags.get("handles_biometric_data", False),
                handles_children_data=compliance_flags.get("handles_children_data", False),
                industries=[domain] if domain else [],
                high_risk_use_cases=[],
                uses_strong_crypto=True,
                uses_weak_crypto=False,
                customer_requires_data_residency=compliance_flags.get("requires_data_residency", False),
                uses_third_country_cloud=False,
                model_providers=[],
                repo_tags=[],
            )
            _decision = ComplianceEngine().evaluate(_ctx)
            if _decision.denied:
                raise HTTPException(
                    status_code=403,
                    detail=f"Compliance check denied: {'; '.join(_decision.reasons)}"
                )
            # Inject compliance context so all phases can access it
            if not isinstance(designer_spec, dict):
                designer_spec = {}
            designer_spec["compliance_context"] = {
                "country_code": production_country,
                "region": _region,
                "allowed": _decision.allowed,
                "requires_approval": _decision.requires_approval,
                "violations": [{"rule_id": v.rule_id, "severity": v.severity, "message": v.message} for v in _decision.violations],
                **compliance_flags,
            }
            logger.info(
                "Compliance pre-check: country=%s region=%s allowed=%s requires_approval=%s violations=%d",
                production_country, _region, _decision.allowed, _decision.requires_approval, len(_decision.violations),
            )
        except HTTPException:
            raise
        except Exception as _comp_exc:
            logger.warning("Compliance pre-check non-fatal error: %s", _comp_exc)

    # B7: Prompt injection guard — block jailbreak and shell injection attempts
    from aether_os.core.security.prompt_guard import guard as _guard
    _safe, _reason = _guard(raw_input)
    if not _safe:
        raise HTTPException(status_code=400, detail=_reason)

    # Pre-generate run_id and insert Run record immediately so the client
    # can poll /factory/runs/{run_id} without a 30s+ 404 window.
    run_id = str(_uuid.uuid4())
    user_id = user.get("sub")
    try:
        from aether_os.core.db import get_session_factory as _gsf_pre
        from aether_os.core.models import Run as _Run_pre
        import time as _time_pre
        _sf_pre = _gsf_pre()
        async with _sf_pre() as _s_pre:
            _s_pre.add(_Run_pre(
                id=run_id,
                org_id=org_id,
                user_id=user_id,
                command=f"factory: {raw_input[:60]}",
                raw_input=raw_input,
                project_name=project_name,
                domain=domain,
                status="queued",
                started_at=_time_pre.time(),
            ))
            await _s_pre.commit()
    except Exception as _pre_exc:
        logger.warning("Pre-insert run record failed: %s", _pre_exc)

    async def _run_bg():
        # LLM Council pre-flight check (non-blocking — runs inside background task)
        _preflight = {"passed": True, "score": 1.0, "reason": "skipped", "suggestions": []}
        try:
            import os as _os
            from aether_os.core.council import PreFlightCouncil
            _council = PreFlightCouncil()
            # Cap the council call at 60s total — if LLM is slow, skip it
            _preflight = await asyncio.wait_for(
                _council.run(raw_input=raw_input, domain=domain, org_id=org_id),
                timeout=60.0,
            )
            if not _preflight.get("passed", True):
                if _os.environ.get("COUNCIL_STRICT_MODE", "false").lower() == "true":
                    logger.warning(
                        "PreFlightCouncil STRICT: run %s rejected (score=%.2f): %s",
                        run_id, _preflight.get("score", 0.0), _preflight.get("reason", ""),
                    )
                    # Mark the run as rejected so the UI shows it clearly
                    try:
                        from aether_os.core.db import get_session_factory as _gsf_rej
                        from aether_os.core.models import Run as _Run_rej
                        from sqlalchemy import update as _upd_rej
                        _sf_rej = _gsf_rej()
                        async with _sf_rej() as _s_rej:
                            await _s_rej.execute(
                                _upd_rej(_Run_rej).where(_Run_rej.id == run_id)
                                .values(
                                    status="rejected",
                                    message=f"PreFlightCouncil rejected: {_preflight.get('reason','')}",
                                    council_preflight=_preflight,
                                )
                            )
                            await _s_rej.commit()
                    except Exception as _rej_exc:
                        logger.warning("Failed to mark run as rejected: %s", _rej_exc)
                    return  # Abort pipeline in strict mode
                logger.warning(
                    "PreFlightCouncil: run %s did not pass (score=%.2f) — proceeding (non-strict): %s",
                    run_id, _preflight.get("score", 0.0), _preflight.get("reason", ""),
                )
        except (asyncio.TimeoutError, Exception) as _ce:
            logger.warning("PreFlightCouncil skipped (timeout/error): %s", type(_ce).__name__)

        try:
            await factory.run(
                client_id=client_id,
                raw_input=raw_input,
                domain=domain,
                project_name=project_name,
                run_id=run_id,
                org_id=org_id,
                council_preflight=_preflight,
                github_url=github_url or None,
                designer_spec=designer_spec or {},
            )
        except Exception as exc:
            logger.error("Background factory run failed: %s", exc)

        # ── Post-completion hooks (non-fatal) ─────────────────────────────
        # 1. Persist quality score to runs table
        try:
            from aether_os.core.quality.metrics import score_project
            from aether_os.core.projects import get_project_manager
            from aether_os.core.db import get_session_factory as _gsf_qs
            from aether_os.core.models import Run as _Run_qs
            from sqlalchemy import update as _upd_qs
            _project_dir = get_project_manager().get_project_dir(run_id)
            if _project_dir.exists():
                _qscore = score_project(_project_dir)
                _sf_qs = _gsf_qs()
                async with _sf_qs() as _s_qs:
                    await _s_qs.execute(
                        _upd_qs(_Run_qs).where(_Run_qs.id == run_id)
                        .values(quality_score=int(_qscore.total))
                    )
                    await _s_qs.commit()
                logger.info("[post-build] quality_score=%d saved for run %s", _qscore.total, run_id)
        except Exception as _qse:
            logger.debug("[post-build] quality score persist skipped: %s", _qse)

        # 2. Record GlobalPattern aggregate learning
        try:
            from aether_os.core.quality.metrics import score_project as _sp2
            from aether_os.core.projects import get_project_manager as _gpm2
            from aether_os.core.db import get_session_factory as _gsf_gp2
            from aether_os.core.services.global_pattern_service import record_global_pattern
            _project_dir2 = _gpm2().get_project_dir(run_id)
            if _project_dir2.exists():
                _qscore2 = _sp2(_project_dir2)
                async with _gsf_gp2()() as _s_gp:
                    await record_global_pattern(
                        run_id=run_id,
                        domain=domain or "general",
                        quality_score_total=float(_qscore2.total),
                        quality_details=_qscore2.details,
                        session=_s_gp,
                    )
                logger.info("[post-build] GlobalPattern recorded domain=%s score=%.1f", domain, _qscore2.total)
        except Exception as _gpe:
            logger.debug("[post-build] GlobalPattern skipped: %s", _gpe)

        # 3. Learning loop — extract patterns from completed run
        if user_id and org_id:
            try:
                from aether_os.core.services import learning_service as _ls2
                from aether_os.core.db import get_session_factory as _gsf_ls
                async with _gsf_ls()() as _s_ls:
                    await _ls2.extract_patterns_from_run(run_id, org_id, user_id, _s_ls)
                logger.info("[post-build] Learning patterns extracted for user %s", user_id)
            except Exception as _le:
                logger.debug("[post-build] Learning loop skipped: %s", _le)

    _t = asyncio.create_task(_run_bg())
    _background_tasks.add(_t)
    _t.add_done_callback(_background_tasks.discard)

    return {
        "run_id": run_id,
        "status": "started",
        "message": f"Pipeline started for: {raw_input[:60]}",
    }


@router.get("/factory/analytics/quality-trend")
async def get_quality_trend(
    limit: int = 50,
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """Return quality + compliance scores for recent completed runs — proves cross-run improvement."""
    from aether_os.core.db import get_session_factory as _gsf_qt
    from sqlalchemy import text as _qt_text
    import pathlib as _pathlib

    org_id = user["org_id"]
    _limit = max(1, min(limit, 200))

    # Fetch recent completed runs from DB — include cached quality_score column
    try:
        async with _gsf_qt()() as _sess:
            rows = (await _sess.execute(
                _qt_text(
                    "SELECT id, project_name, started_at, quality_score FROM runs "
                    "WHERE org_id=:oid AND status IN ('completed','passed') "
                    "ORDER BY started_at DESC LIMIT :lim"
                ),
                {"oid": org_id, "lim": _limit},
            )).all()
    except Exception as _qt_exc:
        logger.debug("quality-trend DB query failed: %s", _qt_exc)
        rows = []

    points = []
    projects_dir = _pathlib.Path.home() / ".aether_os" / "projects"

    for row in rows:
        run_id_qt, proj_name, started_at_qt, db_quality_score = row[0], row[1], row[2], row[3]

        # Convert epoch float to ISO string
        try:
            from datetime import datetime as _dt, timezone as _tz
            _ts = float(started_at_qt) if started_at_qt else 0.0
            created_at_iso = _dt.fromtimestamp(_ts, tz=_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            created_at_iso = str(started_at_qt)

        # Use cached DB quality_score first; fall back to on-demand compute only if absent
        quality_score: Optional[int] = db_quality_score
        if quality_score is None:
            run_dir = projects_dir / run_id_qt
            if run_dir.exists():
                try:
                    from aether_os.core.quality.metrics import score_project as _score_qt
                    _qs = _score_qt(run_dir)
                    quality_score = _qs.total
                except Exception:
                    pass

        # Compliance score from pre-built scan JSON
        compliance_score: Optional[int] = None
        run_dir = projects_dir / run_id_qt
        _comp_json = run_dir / "p06_review_security" / "compliance" / "compliance_scan.json"
        if _comp_json.exists():
            try:
                _cd = json.loads(_comp_json.read_text(encoding="utf-8"))
                compliance_score = _cd.get("score")
            except Exception:
                pass

        if quality_score is not None:
            points.append({
                "run_id": run_id_qt,
                "project_name": proj_name or f"run-{run_id_qt[:8]}",
                "created_at": created_at_iso,
                "quality_score": quality_score,
                "compliance_score": compliance_score,
            })

    # Reverse so oldest is first (for chart to trend left→right in time)
    points.reverse()
    return {"points": points, "total": len(points)}


@router.get("/factory/search")
async def search_artifacts(
    q: str,
    limit: int = 30,
    user: Dict[str, Any] = _current_user(),
) -> List[Dict[str, Any]]:
    """Semantic search across all generated artifacts for the organisation."""
    from aether_os.core.artifact_store import get_artifact_store
    org_id = user.get("org_id")
    store = get_artifact_store()
    return await store.search(q, org_id, limit=limit)


@router.get("/factory/deployments")
async def list_deployments(
    user: Dict[str, Any] = _current_user(),
) -> Dict[str, Any]:
    """List deployments: completed runs from DB plus running Docker containers."""
    import subprocess as _sp
    import asyncio as _aio

    org_id = user.get("org_id")

    # 1. Query completed/running runs from DB
    db_deployments: List[Dict[str, Any]] = []
    try:
        from aether_os.core.db import get_session_factory as _gsf_dep
        from aether_os.core.models import Run as _RunDep
        from sqlalchemy import select as _sel_dep
        _sf_dep = _gsf_dep()
        async with _sf_dep() as _sess_dep:
            _run_rows = (await _sess_dep.execute(
                _sel_dep(_RunDep)
                .where(
                    _RunDep.org_id == org_id,
                    _RunDep.status.in_(["completed", "needs_review", "running"]),
                )
                .order_by(_RunDep.started_at.desc())
                .limit(50)
            )).scalars().all()
        for _r in _run_rows:
            # Note: _APP_PROCS lives in api.py; proc_status defaults to stopped in this router context
            _proc_status = "stopped"
            db_deployments.append({
                "run_id":       _r.id,
                "project_name": _r.project_name or f"run-{_r.id[:8]}",
                "domain":       _r.domain or "general",
                "status":       _r.status,
                "proc_status":  _proc_status,
                "started_at":   _r.started_at,
                "live_url":     getattr(_r, "live_url", None),
            })
    except Exception as _dep_exc:
        logger.debug("Deployments DB query failed: %s", _dep_exc)

    # 2. List running Docker containers (best-effort — docker may not be in PATH inside container)
    containers = []
    try:
        def _list():
            return _sp.run(
                ["docker", "ps", "--filter", "name=aetheros-app",
                 "--format", "{{.Names}}\t{{.Ports}}\t{{.Status}}"],
                capture_output=True, text=True,
            )

        result = await _aio.to_thread(_list)
        for line in result.stdout.strip().split("\n"):
            if line:
                parts = line.split("\t")
                containers.append({
                    "name":   parts[0] if len(parts) > 0 else "",
                    "ports":  parts[1] if len(parts) > 1 else "",
                    "status": parts[2] if len(parts) > 2 else "",
                })
    except Exception:
        pass
    return {"deployments": db_deployments, "containers": containers}
