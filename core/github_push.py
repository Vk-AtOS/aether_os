"""Push a whole clean export to a GitHub repository as ONE commit (KAN-269).

The old push did one ``PUT /contents`` per file, stopped at 50 files, never looked at the response status and
reported success whatever GitHub said. This uses the git data API instead:

  1. make sure the branch has a commit (a new empty repository has none, and the git data API refuses it);
  2. upload every file as a blob, in concurrent batches, retrying rate-limit and 5xx answers;
  3. if ANY blob failed, stop and raise ``PushError`` listing each failed file - nothing is committed, so a
     half-uploaded project never appears as a finished repository;
  4. build the tree in chunks, create one commit, move the branch to it.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

API = "https://api.github.com"
BLOB_BATCH = 20          # concurrent blob uploads
TREE_CHUNK = 200         # entries per tree request
RETRIES = 3


class PushError(Exception):
    """The push failed; `errors` is one entry per failed file or step (path, status, message)."""

    def __init__(self, message: str, errors: Optional[List[Dict[str, object]]] = None):
        super().__init__(message)
        self.errors = errors or []


async def _call(gh: httpx.AsyncClient, method: str, url: str, **kw) -> httpx.Response:
    """One GitHub call; rate limits (403/429 with Retry-After) and 5xx are retried, everything else returned."""
    resp: Optional[httpx.Response] = None
    for attempt in range(RETRIES):
        try:
            resp = await gh.request(method, url, **kw)
        except httpx.HTTPError as e:
            if attempt == RETRIES - 1:
                raise PushError(f"{method} {url} failed: {e}") from e
            await asyncio.sleep(0.5 * (attempt + 1))
            continue
        retry_after = resp.headers.get("retry-after")
        limited = resp.status_code in (403, 429) and (retry_after is not None or "rate limit" in resp.text.lower())
        if (limited or resp.status_code >= 500) and attempt < RETRIES - 1:
            await asyncio.sleep(min(float(retry_after or 0.5 * (attempt + 1)), 30))
            continue
        return resp
    assert resp is not None
    return resp


def _detail(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("message", resp.text))[:200]
    except ValueError:
        return resp.text[:200]


async def _ensure_base_commit(gh: httpx.AsyncClient, repo: str, branch: str,
                              seed: Tuple[str, bytes]) -> Tuple[str, str]:
    """(commit sha, tree sha) of the branch head; a brand-new repository is first given `seed` as its first commit."""
    ref = await _call(gh, "GET", f"{API}/repos/{repo}/git/ref/heads/{branch}")
    if ref.status_code == 404 or ref.status_code == 409:
        path, data = seed
        put = await _call(gh, "PUT", f"{API}/repos/{repo}/contents/{path}", json={
            "message": f"Add {path}", "content": base64.b64encode(data).decode(), "branch": branch})
        if put.status_code not in (200, 201):
            raise PushError(f"could not create the first commit on {branch}: {_detail(put)}",
                            [{"path": path, "status": put.status_code, "message": _detail(put)}])
        sha = put.json()["commit"]["sha"]
    elif ref.status_code == 200:
        sha = ref.json()["object"]["sha"]
    else:
        raise PushError(f"could not read branch {branch}: {_detail(ref)}",
                        [{"path": f"refs/heads/{branch}", "status": ref.status_code, "message": _detail(ref)}])
    commit = await _call(gh, "GET", f"{API}/repos/{repo}/git/commits/{sha}")
    if commit.status_code != 200:
        raise PushError(f"could not read commit {sha}: {_detail(commit)}")
    return sha, commit.json()["tree"]["sha"]


async def push_files(token: str, repo: str, files: List[Tuple[str, bytes]], branch: str = "main",
                     message: str = "Initial commit from AetherOS", client: Optional[httpx.AsyncClient] = None) -> dict:
    """Push `files` ((path, bytes) pairs) to `repo` ("owner/name") as one commit on `branch`.

    Raises PushError (with per-file errors) if anything fails; returns {commit_sha, files_pushed, branch}.
    """
    if not files:
        raise PushError("nothing to push: the export has no files")
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    own = client is None
    gh = client or httpx.AsyncClient(timeout=60, headers=headers)
    if not own:
        gh.headers.update(headers)
    try:
        seed = next(((p, d) for p, d in files if p == "README.md"), files[0])
        parent, base_tree = await _ensure_base_commit(gh, repo, branch, seed)

        errors: List[Dict[str, object]] = []
        entries: List[dict] = []

        async def blob(path: str, data: bytes) -> None:
            r = await _call(gh, "POST", f"{API}/repos/{repo}/git/blobs",
                            json={"content": base64.b64encode(data).decode(), "encoding": "base64"})
            if r.status_code != 201:
                errors.append({"path": path, "status": r.status_code, "message": _detail(r)})
                return
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": r.json()["sha"]})

        for i in range(0, len(files), BLOB_BATCH):
            await asyncio.gather(*(blob(p, d) for p, d in files[i:i + BLOB_BATCH]))
        if errors:
            raise PushError(f"{len(errors)} of {len(files)} files failed to upload; nothing was committed", errors)

        entries.sort(key=lambda e: e["path"])
        tree_sha = base_tree
        for i in range(0, len(entries), TREE_CHUNK):
            r = await _call(gh, "POST", f"{API}/repos/{repo}/git/trees",
                            json={"base_tree": tree_sha, "tree": entries[i:i + TREE_CHUNK]})
            if r.status_code != 201:
                raise PushError(f"tree creation failed: {_detail(r)}", [{"path": "(tree)", "status": r.status_code, "message": _detail(r)}])
            tree_sha = r.json()["sha"]
        c = await _call(gh, "POST", f"{API}/repos/{repo}/git/commits",
                        json={"message": message, "tree": tree_sha, "parents": [parent]})
        if c.status_code != 201:
            raise PushError(f"commit creation failed: {_detail(c)}", [{"path": "(commit)", "status": c.status_code, "message": _detail(c)}])
        commit_sha = c.json()["sha"]
        u = await _call(gh, "PATCH", f"{API}/repos/{repo}/git/refs/heads/{branch}", json={"sha": commit_sha})
        if u.status_code != 200:
            raise PushError(f"could not move {branch} to the new commit: {_detail(u)}",
                            [{"path": f"refs/heads/{branch}", "status": u.status_code, "message": _detail(u)}])
        logger.info("github_push: %d files pushed to %s@%s as %s", len(files), repo, branch, commit_sha[:8])
        return {"commit_sha": commit_sha, "files_pushed": len(files), "branch": branch}
    finally:
        if own:
            await gh.aclose()
