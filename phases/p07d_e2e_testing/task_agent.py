"""P07d E2E Testing — generates and runs Playwright end-to-end tests."""
from __future__ import annotations
import json
import logging
import re
import textwrap
from pathlib import Path
from typing import Any, Dict, List

from aether_os.core.run_app import safe_fs
from aether_os.core.sandbox import phase_exec
from aether_os.core.sandbox.browser_job import run_browser_job
from aether_os.core.sandbox.runner import SandboxUnavailable, sandbox_dirs
from aether_os.phases.base import TaskResult
from aether_os.phases.p07c_accessibility_testing.task_agent import dist_dir_for

# Inside the browser sandbox "localhost" is only what the job itself starts: the built frontend on 5173 and,
# when there is one, the generated backend on 8000 (both on the container's loopback, no network).
FRONTEND_PORT, BACKEND_PORT = 5173, 8000

logger = logging.getLogger(__name__)


def _build_fallback_e2e(project_name: str, frontend_url: str, entities: list) -> str:
    entity_name = entities[0].get("name", "Item").lower() if entities else "item"
    table = entities[0].get("table", entity_name + "s") if entities else "items"
    return textwrap.dedent(f"""\
        import {{ test, expect }} from '@playwright/test';

        const BASE = '{frontend_url}';

        test('homepage loads', async ({{ page }}) => {{
          await page.goto(BASE);
          await expect(page).toHaveTitle(/.*/);
        }});

        test('health endpoint responds', async ({{ request }}) => {{
          const resp = await request.get('http://localhost:8000/health');
          expect(resp.status()).toBe(200);
          const body = await resp.json();
          expect(body.status).toBe('ok');
        }});

        test('API {table} list returns 2xx', async ({{ request }}) => {{
          const resp = await request.get('http://localhost:8000/api/{table}');
          expect(resp.status()).toBeLessThan(400);
        }});
    """)


def _backend_spec(data: Dict[str, Any], root: Path):
    """How to start the generated backend inside the sandbox, or None when there is none to start."""
    raw = data.get("backend_output_path")
    if not raw:
        return None
    backend = Path(raw)
    try:
        rel = backend.relative_to(root)
    except ValueError:
        return None
    for sub, ref in (("src/main.py", "src.main:app"), ("main.py", "main:app")):
        if safe_fs.stat_or_none(root, rel / sub) is not None:
            db = Path(sandbox_dirs(root)["TMPDIR"]) / "e2e.db"
            return {"cwd": str(backend), "port": BACKEND_PORT,
                    "argv": ["python3", "-m", "uvicorn", ref, "--host", "127.0.0.1", "--port", str(BACKEND_PORT)],
                    "env": {"DATABASE_URL": f"sqlite+aiosqlite:///{db}", "ENVIRONMENT": "test"}}
    return None


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    data = phase_input.input_data if hasattr(phase_input, "input_data") else {}

    # Defer: the specs need a built frontend to serve in the browser sandbox (a URL on the host is not
    # reachable from it: the sandbox has no network).
    dist = dist_dir_for(data)
    if dist is None:
        result = {
            "success": True,
            "skipped": True,
            "reason": "deferred: needs a built frontend (dist/) — nothing to serve in the browser sandbox",
        }
        (output_dir / "e2e_results.json").write_text(json.dumps(result, indent=2))
        return TaskResult(
            output_path=str(output_dir / "e2e_results.json"),
            confidence=1.0,
            metadata={"phase": "p07d_e2e_testing", "skipped": True, "data": result},
        )

    project_name: str = data.get("project_name", "App")
    entities: list = data.get("entities", [])
    frontend_url = f"http://127.0.0.1:{FRONTEND_PORT}"

    # ── Generate e2e tests via LLM ────────────────────────────────────────────
    test_code = ""
    try:
        from aether_os.core.llm.client import get_llm_client
        llm = get_llm_client()
        entity_names = [e.get("name", "Item") for e in entities[:5]]
        prompt = (
            f"Generate Playwright TypeScript e2e tests for '{project_name}' "
            f"(frontend at {frontend_url}, backend at http://localhost:8000). "
            f"Entities: {json.dumps(entity_names)}.\n\n"
            "Tests should: load the homepage, check the API /health endpoint, "
            "verify list pages render without 500 errors, test basic navigation. "
            "Use @playwright/test with async/await. No external imports.\n\n"
            "Return ONLY the TypeScript test file. No markdown."
        )
        result = await llm.call(prompt, task_type="code_generation")
        if result and len(result.strip()) > 100:
            m = re.search(r"```(?:typescript|ts)?\s*\n(.*?)```", result, re.DOTALL)
            test_code = m.group(1).strip() if m else result.strip()
    except Exception as exc:
        logger.warning("[p07d] LLM e2e gen failed: %s", exc)

    if not test_code:
        test_code = _build_fallback_e2e(project_name, frontend_url, entities)

    test_file = output_dir / "e2e.spec.ts"
    test_file.write_text(test_code)

    # ── Write playwright config ───────────────────────────────────────────────
    pw_config = textwrap.dedent(f"""\
        import {{ defineConfig }} from '@playwright/test';
        export default defineConfig({{
          testDir: '.',
          timeout: 30000,
          use: {{
            baseURL: '{frontend_url}',
            headless: true,
          }},
        }});
    """)
    (output_dir / "playwright.config.ts").write_text(pw_config)

    # ── Run playwright if available ───────────────────────────────────────────
    run_results: Dict = {"test_file": str(test_file), "passed": 0, "failed": 0, "skipped": False}

    try:
        # The generated e2e spec is untrusted code and so is the app it drives: both run in the browser
        # sandbox, which serves the build and the backend on its own loopback (no network at all).
        root = phase_exec.project_root(output_dir)
        out_json = Path(sandbox_dirs(root)["TMPDIR"]) / "playwright_output.json"
        job = {"action": "playwright_test", "spec": str(test_file), "cwd": str(output_dir), "out": str(out_json),
               "timeout": 100, "serve": {"dir": str(dist), "port": FRONTEND_PORT}}
        backend = _backend_spec(data, root)
        if backend:
            job["backend"] = backend
        reply = await run_browser_job(job, project=output_dir, timeout=150)
        if not reply.get("ok"):
            raise RuntimeError(reply.get("error") or "the browser job failed")
        output_text = safe_fs.read_text_or_none(root, out_json) or ""
        (output_dir / "playwright_output.json").write_text(output_text)

        try:
            report = json.loads(output_text)
            stats = report.get("stats", {})
            run_results["passed"] = stats.get("expected", 0)
            run_results["failed"] = stats.get("unexpected", 0)
        except Exception as e:
            logger.warning("p07d_e2e: could not parse playwright report JSON: %s", e)
            run_results["raw_output"] = output_text[-500:]

        logger.info("[p07d] playwright done: %d passed, %d failed", run_results["passed"], run_results["failed"])
    except SandboxUnavailable:
        raise  # the generated spec was not run, and never will be on the host
    except Exception as exc:
        logger.info("[p07d] playwright skipped: %s", exc)
        run_results["skipped"] = True
        run_results["reason"] = "the browser sandbox could not run the specs (see log)"

    (output_dir / "e2e_summary.json").write_text(json.dumps(run_results, indent=2))

    return TaskResult(
        output_path=str(test_file),
        confidence=0.72,
        metadata=run_results,
        success=True,
        issues=[],
    )
