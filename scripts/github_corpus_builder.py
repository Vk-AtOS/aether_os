#!/usr/bin/env python3
"""
GitHub FastAPI Entity Pattern Corpus Builder.

Uses the GitHub API to find top-starred FastAPI + SQLAlchemy repos,
downloads their models.py, schemas.py, and crud.py files, extracts
entity patterns, and stores them in:
  core/knowledge_graph/golden_examples/github_entity_patterns.json

Usage:
    python3 scripts/github_corpus_builder.py [--token GITHUB_TOKEN] [--limit 50] [--output PATH]

Rate limit: 5,000 requests/hour with token, 60/hour without.
Without a token, the script will collect ~20 repos before hitting the limit.
"""
from __future__ import annotations

import argparse
import ast
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("github_corpus_builder")

# ── Constants ──────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_OUTPUT = (
    REPO_ROOT / "core" / "knowledge_graph" / "golden_examples" / "github_entity_patterns.json"
)
GH_API = "https://api.github.com"
GH_SEARCH = f"{GH_API}/search/repositories"
GH_RAW = "https://raw.githubusercontent.com"

# Files to attempt to download from each repo
TARGET_FILES = ["models.py", "app/models.py", "src/models.py",
                "schemas.py", "app/schemas.py", "src/schemas.py",
                "crud.py", "app/crud.py", "src/crud.py"]

# Domain keywords inferred from repo description/topics
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "ecommerce":  ["shop", "store", "ecommerce", "product", "cart", "order", "payment"],
    "healthcare": ["health", "patient", "clinic", "medical", "hospital", "appointment"],
    "fintech":    ["finance", "bank", "payment", "invoice", "transaction", "account"],
    "saas":       ["saas", "tenant", "subscription", "api", "platform", "workspace"],
    "hrtech":     ["hr", "employee", "payroll", "recruit", "talent", "leave"],
}


# ── Argument parsing ───────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""),
                   help="GitHub personal access token (or set GITHUB_TOKEN env var)")
    p.add_argument("--limit", type=int, default=50,
                   help="Number of repos to process (default: 50)")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                   help=f"Output JSON path (default: {DEFAULT_OUTPUT})")
    return p.parse_args()


# ── GitHub API helpers ─────────────────────────────────────────────────────────


def _gh_headers(token: str) -> dict[str, str]:
    headers: dict[str, str] = {"Accept": "application/vnd.github+json",
                                "User-Agent": "github-corpus-builder/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _gh_get(url: str, token: str, params: dict | None = None,
            retries: int = 3) -> dict | list | None:
    """GET a GitHub API URL, handling rate limits and transient errors."""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=_gh_headers(token))
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 429 or exc.code == 403:
                # Rate-limited: read Retry-After header or default to 60 s
                retry_after = int(exc.headers.get("Retry-After", "60"))
                logger.warning("Rate limited (HTTP %d). Sleeping %ds …", exc.code, retry_after)
                time.sleep(retry_after)
                continue
            if exc.code == 404:
                return None
            logger.warning("HTTP %d for %s (attempt %d/%d)", exc.code, url, attempt + 1, retries)
            if attempt == retries - 1:
                return None
            time.sleep(2 ** attempt)
        except urllib.error.URLError as exc:
            logger.warning("URLError for %s: %s", url, exc)
            if attempt == retries - 1:
                return None
            time.sleep(2 ** attempt)
        except Exception as exc:
            logger.warning("Unexpected error for %s: %s", url, exc)
            return None
    return None


def _fetch_raw(owner: str, repo: str, branch: str, filepath: str, token: str) -> str | None:
    """Download raw file content from GitHub."""
    url = f"{GH_RAW}/{owner}/{repo}/{branch}/{filepath}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "github-corpus-builder/1.0"})
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            logger.debug("HTTP %d fetching %s/%s/%s", exc.code, owner, repo, filepath)
        return None
    except Exception as exc:
        logger.debug("Error fetching %s/%s/%s: %s", owner, repo, filepath, exc)
        return None


# ── AST entity extraction ──────────────────────────────────────────────────────


def _extract_entities_from_source(source: str) -> list[dict]:
    """Parse Python source and extract SQLAlchemy model class definitions."""
    entities: list[dict] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return entities

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        # Check for SQLAlchemy Base inheritance pattern
        bases = [ast.unparse(b) for b in node.bases] if hasattr(ast, "unparse") else []
        is_model = any(
            "Base" in b or "Model" in b or "SQLModel" in b or "DeclarativeBase" in b
            for b in bases
        )
        if not is_model:
            continue

        fields: list[dict] = []
        relationships: list[dict] = []
        indexes: list[str] = []

        for item in node.body:
            if not isinstance(item, ast.Assign):
                continue
            for target in item.targets:
                if not isinstance(target, ast.Name):
                    continue
                field_name = target.id
                if field_name.startswith("__"):
                    continue

                # Detect Column() calls
                value = item.value
                if isinstance(value, ast.Call):
                    func_name = ""
                    if isinstance(value.func, ast.Name):
                        func_name = value.func.id
                    elif isinstance(value.func, ast.Attribute):
                        func_name = value.func.attr

                    if func_name == "Column":
                        field_info: dict = {"name": field_name}
                        # Extract type from first arg
                        if value.args:
                            first = value.args[0]
                            if isinstance(first, ast.Call) and isinstance(first.func, ast.Name):
                                field_info["type"] = first.func.id.lower()
                            elif isinstance(first, ast.Name):
                                field_info["type"] = first.id.lower()
                        # Detect FK
                        for kw in value.keywords:
                            if kw.arg is None and isinstance(kw.value, ast.Call):
                                # ForeignKey() call
                                if (isinstance(kw.value.func, ast.Name) and
                                        kw.value.func.id == "ForeignKey"):
                                    if kw.value.args:
                                        try:
                                            field_info["foreign_key"] = ast.literal_eval(
                                                kw.value.args[0])
                                        except Exception:
                                            pass
                            elif kw.arg == "primary_key" and isinstance(kw.value, ast.Constant):
                                if kw.value.value:
                                    field_info["primary_key"] = True
                            elif kw.arg == "index" and isinstance(kw.value, ast.Constant):
                                if kw.value.value:
                                    indexes.append(field_name)
                        fields.append(field_info)

                    elif func_name == "relationship":
                        rel_info: dict = {"name": field_name}
                        if value.args:
                            first = value.args[0]
                            if isinstance(first, ast.Constant):
                                rel_info["target"] = first.value
                        relationships.append(rel_info)

        if fields:
            entity: dict = {"name": node.name, "fields": fields}
            if relationships:
                entity["relationships"] = relationships
            if indexes:
                entity["indexes"] = indexes
            entities.append(entity)

    return entities


# ── Domain inference ───────────────────────────────────────────────────────────


def _infer_domain(repo: dict) -> str:
    """Infer domain from repo description and topics."""
    text = " ".join([
        repo.get("description") or "",
        " ".join(repo.get("topics", [])),
        repo.get("name", ""),
    ]).lower()
    for domain, keywords in DOMAIN_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return domain
    return "saas"  # default


# ── Main corpus building logic ─────────────────────────────────────────────────


def _search_repos(token: str, limit: int) -> list[dict]:
    """Search GitHub for FastAPI + SQLAlchemy repos, return repo objects."""
    queries = [
        "language:python fastapi sqlalchemy stars:>100",
        "language:python fastapi sqlalchemy stars:>50",
        "language:python fastapi pydantic sqlalchemy stars:>30",
    ]
    seen: set[str] = set()
    repos: list[dict] = []

    for q in queries:
        if len(repos) >= limit:
            break
        params = {"q": q, "sort": "stars", "order": "desc", "per_page": 30}
        data = _gh_get(GH_SEARCH, token, params)
        if not data or not isinstance(data, dict):
            continue
        for item in data.get("items", []):
            full_name = item.get("full_name", "")
            if full_name in seen:
                continue
            seen.add(full_name)
            repos.append(item)
            if len(repos) >= limit:
                break

    logger.info("Found %d candidate repos.", len(repos))
    return repos


def _process_repo(repo: dict, token: str) -> list[dict]:
    """Download target files from a repo, extract entity patterns."""
    owner = repo["owner"]["login"]
    name = repo["name"]
    branch = repo.get("default_branch", "main")
    domain = _infer_domain(repo)
    url = repo.get("html_url", "")

    entities: list[dict] = []
    for filepath in TARGET_FILES:
        source = _fetch_raw(owner, name, branch, filepath, token)
        if not source:
            continue
        extracted = _extract_entities_from_source(source)
        for ent in extracted:
            # Build the sqlalchemy model output string
            field_lines = []
            for f in ent.get("fields", []):
                fname = f["name"]
                ftype = f.get("type", "String")
                pk = ", primary_key=True, index=True" if f.get("primary_key") else ""
                fk = f", ForeignKey('{f['foreign_key']}')" if f.get("foreign_key") else ""
                idx = ", index=True" if fname in ent.get("indexes", []) else ""
                field_lines.append(f"    {fname} = Column({ftype.capitalize()}{fk}{pk}{idx})")

            rel_lines = []
            for r in ent.get("relationships", []):
                target = r.get("target", "Unknown")
                rel_lines.append(f"    {r['name']} = relationship('{target}')")

            all_lines = (
                [f"class {ent['name']}(Base):"]
                + [f"    __tablename__ = '{ent['name'].lower()}s'"]
                + field_lines
                + rel_lines
            )
            output_code = "\n".join(all_lines)

            entities.append({
                "domain": domain,
                "entity_name": ent["name"],
                "fields": ent.get("fields", []),
                "source_repo": f"github.com/{owner}/{name}",
                "source_url": url,
                "output_code": output_code,
            })
    return entities


def _build_example(idx: int, ent_data: dict) -> dict:
    """Convert extracted entity data into the golden example schema."""
    input_fields = [
        {"name": f.get("name", ""), "type": f.get("type", "str"),
         **({"primary_key": True} if f.get("primary_key") else {}),
         **({"foreign_key": f["foreign_key"]} if f.get("foreign_key") else {})}
        for f in ent_data.get("fields", [])
    ]
    return {
        "id": f"gh_{idx:04d}",
        "type": "entity_to_sqlalchemy",
        "domain": ent_data.get("domain", "saas"),
        "tags": ["model", "sqlalchemy", "fastapi"],
        "input": {
            "name": ent_data["entity_name"],
            "fields": input_fields,
        },
        "output": ent_data["output_code"],
        "source": ent_data.get("source_url", ""),
    }


def _write_output(examples: list[dict], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "domain": "cross_domain",
        "version": "1.0",
        "generated_at": time.strftime("%Y-%m-%d"),
        "source": "github_api",
        "examples": examples,
    }
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    logger.info("Wrote %d examples to %s", len(examples), output)


# ── Entry point ────────────────────────────────────────────────────────────────


def main() -> None:
    args = _parse_args()
    token = args.token

    if not token:
        logger.warning(
            "No GitHub token provided. Rate limit is 60 req/hour. "
            "Set --token or GITHUB_TOKEN env var for 5,000 req/hour."
        )

    logger.info("github_corpus_builder starting — limit=%d repos, output=%s", args.limit, args.output)

    repos = _search_repos(token, args.limit)
    if not repos:
        logger.error("No repos found. Check network connectivity and GitHub token.")
        sys.exit(1)

    all_entities: list[dict] = []
    for i, repo in enumerate(repos):
        logger.info("[%d/%d] Processing %s …", i + 1, len(repos), repo.get("full_name"))
        try:
            ents = _process_repo(repo, token)
            all_entities.extend(ents)
            logger.info("  → %d entities extracted", len(ents))
        except Exception as exc:
            logger.warning("Skipping %s due to error: %s", repo.get("full_name"), exc)
        # Be polite to the API
        time.sleep(0.5)

    if not all_entities:
        logger.warning("No entity patterns extracted. Repos may not have parseable models.py files.")
        sys.exit(0)

    examples = [_build_example(i + 1, e) for i, e in enumerate(all_entities)]
    _write_output(examples, args.output)
    logger.info("Done. Extracted %d entity patterns from %d repos.", len(examples), len(repos))


if __name__ == "__main__":
    main()
