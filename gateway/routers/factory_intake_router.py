"""
AetherOS — Factory Intake Router
Extracted from factory_ops_router.py.

Routes for bringing external data into the pipeline:
  POST /factory/upload-requirement
  POST /factory/fetch-github-repo
  POST /factory/import-schema
  POST /factory/fetch-repo
"""
from __future__ import annotations

import logging
import os
import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File as FastAPIFile
from aether_os.core.security.safe_http import UnsafeURL, check_url_shape, safe_request
from aether_os.gateway.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["factory"])


def _current_user():
    return Depends(get_current_user)


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
                logger.warning("factory_intake: PDF parsing unavailable: %s", e)
                return {"text": "", "error": f"PDF parsing unavailable: {e}"}
    elif ext in ("png", "jpg", "jpeg", "webp"):
        try:
            from aether_os.core.llm.client import get_llm_client
            llm = get_llm_client()
            prompt = (
                "This image is a requirements document, wireframe, or specification screenshot. "
                "Extract ALL visible text and describe every UI element, form field, button, and functional requirement in detail. "
                "Return plain text only — no markdown fences, no commentary."
            )
            extracted = await llm.call_vision(prompt, content)
            if not extracted:
                return {"text": "", "error": "Could not extract text from image — please ensure the image is clear and readable"}
        except Exception as e:
            logger.warning("Vision extraction failed: %s", e)
            return {"text": "", "error": f"Image extraction failed: {e} — please paste text instead"}
    elif ext in ("docx",):
        try:
            import docx
            doc = docx.Document(io.BytesIO(content))
            extracted = "\n".join(p.text for p in doc.paragraphs)
        except Exception as e:
            logger.warning("factory_intake: DOCX parsing failed: %s", e)
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
                except Exception as exc:
                    logger.debug("Failed to decode blob content for file %s: %s", f.get("path"), exc)
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
    # import_schema validates the PARSED url (driver allow-list, sqlite path, public host); a bad string is
    # answered there with {"error", "tables": []}, so the check lives in one place.
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
    import httpx, base64, tempfile, shutil

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
        try:
            check_url_shape(gitlab_base)
        except UnsafeURL as exc:
            raise HTTPException(status_code=422, detail=f"gitlab_url refused: {exc}") from exc

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
            # Self-hosted GitLab: a user-supplied host, so resolve-check-pin every request.
            try:
                tree_res = await safe_request("GET", f"{api_base}/projects/{encoded}/repository/tree?recursive=true&per_page=200", headers=hdrs, timeout=20)
            except UnsafeURL as exc:
                raise HTTPException(status_code=422, detail=f"gitlab_url refused: {exc}") from exc
            if tree_res.status_code == 404:
                raise HTTPException(status_code=404, detail="GitLab project not found or private (provide token)")
            tree = tree_res.json()
            key_files = [f for f in tree if f.get("type") == "blob" and f["name"].lower() in _KEY_FILES][:max_files]
            context_parts.append(f"Repository: {path} (GitLab)")
            for f in key_files:
                fpath = f["path"]
                raw_res = await safe_request("GET", f"{api_base}/projects/{encoded}/repository/files/{fpath.replace('/',  '%2F')}/raw?ref=HEAD", headers=hdrs, timeout=20)
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
                        except Exception as exc:
                            logger.debug("Failed to decode GitHub blob content for %s: %s", f.get("path"), exc)

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
                        except Exception as exc:
                            logger.debug("Failed to read cloned file %s: %s", fpath, exc)
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
