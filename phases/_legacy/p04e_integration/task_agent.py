"""P04e Task Agent — generate typed API client from OpenAPI spec."""
from __future__ import annotations
import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.core.llm.client import get_llm_client

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data
    api_url = data.get("api_url", "http://localhost:8000")
    arch_json = data.get("architecture_json", {})
    if isinstance(arch_json, str):
        try:
            arch_json = json.loads(arch_json)
        except Exception:
            arch_json = {}
    frontend_dir = Path(data.get("frontend_dir", str(output_dir / "frontend")))
    llm = get_llm_client()

    # Try to fetch real OpenAPI spec
    openapi_spec = None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{api_url}/openapi.json")
            if resp.status_code == 200:
                openapi_spec = resp.json()
    except Exception as e:
        logger.info("Could not fetch OpenAPI from %s: %s — generating from arch", api_url, e)

    if not openapi_spec:
        # Generate OpenAPI spec from architecture
        endpoints = arch_json.get("api_endpoints", [])
        openapi_spec = _build_openapi_from_arch(arch_json, endpoints)

    spec_path = output_dir / "openapi.json"
    spec_path.write_text(json.dumps(openapi_spec, indent=2))

    client_dir = output_dir / "api-client"
    client_dir.mkdir(parents=True, exist_ok=True)
    generator_ok = False

    # Try openapi-generator-cli via npx
    try:
        result = subprocess.run(
            ["npx", "@openapitools/openapi-generator-cli", "generate",
             "-i", str(spec_path), "-g", "typescript-axios",
             "-o", str(client_dir)],
            capture_output=True, text=True, timeout=120,
        )
        generator_ok = result.returncode == 0
        if not generator_ok:
            logger.warning("openapi-generator-cli failed: %s", result.stderr[:300])
    except Exception as e:
        logger.info("openapi-generator-cli unavailable: %s — generating client with LLM", e)

    if not generator_ok:
        # Generate typed client with Claude
        endpoints = arch_json.get("api_endpoints", [])
        client_code = await llm.call(
            f"Write a TypeScript API client for these endpoints:\n"
            f"{json.dumps(endpoints, indent=2)[:2000]}\n"
            f"API base URL: {api_url}\n"
            f"Use fetch() with async/await. Include types for all requests/responses. "
            f"Include error handling. Export a default ApiClient class.",
            task_type="code_generation",
        )
        (client_dir / "api_client.ts").write_text(_strip_fences(client_code))

        # Also generate Python client for Python frontends
        py_client = await llm.call(
            f"Write a Python httpx async API client for:\n"
            f"{json.dumps(endpoints, indent=2)[:2000]}\n"
            f"Base URL: {api_url}. Use Pydantic models for responses.",
            task_type="code_generation",
        )
        (client_dir / "api_client.py").write_text(_strip_fences(py_client))

    # Copy client into frontend project
    if frontend_dir.exists():
        api_dir = frontend_dir / "api"
        api_dir.mkdir(exist_ok=True)
        for f in client_dir.glob("*"):
            import shutil
            shutil.copy2(str(f), str(api_dir / f.name))

    client_files = list(client_dir.glob("*"))
    issues = []
    if not client_files:
        issues.append("No client files generated")

    endpoints = arch_json.get("api_endpoints", [])
    if client_dir.exists():
        client_text = " ".join(f.read_text() for f in client_dir.glob("*.ts")
                               if f.is_file())
        missing_methods = []
        for ep in endpoints[:5]:
            path = ep.get("path", "").strip("/").replace("/", "_").replace("{", "").replace("}", "")
            if path and path not in client_text and ep.get("path", "").strip("/") not in client_text:
                missing_methods.append(ep.get("path"))
        if missing_methods:
            issues.append(f"Client missing methods for: {missing_methods[:3]}")

    return TaskResult(
        output_path=str(client_dir),
        confidence=0.85 if not issues else 0.6,
        metadata={"spec_path": str(spec_path), "generator_used": "openapi-generator-cli" if generator_ok else "llm",
                  "client_files": len(client_files)},
        issues=issues,
        success=len(client_files) > 0,
    )


def _build_openapi_from_arch(arch: Dict, endpoints: List[Dict]) -> Dict:
    paths = {}
    for ep in endpoints:
        path = ep.get("path", "/")
        method = ep.get("method", "GET").lower()
        paths.setdefault(path, {})[method] = {
            "summary": ep.get("description", ""),
            "operationId": f"{method}_{path.strip('/').replace('/','_').replace('{','').replace('}','')}",
            "tags": [path.strip("/").split("/")[0] or "default"],
            "responses": {"200": {"description": "Success"}, "422": {"description": "Validation Error"}},
        }
        if ep.get("auth"):
            paths[path][method]["security"] = [{"bearerAuth": []}]
    return {
        "openapi": "3.0.0",
        "info": {"title": "AetherOS Generated API", "version": "1.0.0"},
        "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}},
        "paths": paths,
    }


def _strip_fences(code: str) -> str:
    lines = code.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)
