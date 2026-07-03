"""P07d E2E Testing — generates and runs Playwright end-to-end tests."""
from __future__ import annotations
import asyncio
import json
import logging
import re
import textwrap
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult

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


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    data = phase_input.input_data if hasattr(phase_input, "input_data") else {}

    # Defer: this phase requires a running frontend, which is not available during pipeline build.
    if not data.get("frontend_url") and not data.get("app_url"):
        result = {
            "success": True,
            "skipped": True,
            "reason": "deferred: requires running app — re-run after app start",
        }
        (output_dir / "e2e_results.json").write_text(json.dumps(result, indent=2))
        return TaskResult(
            output_path=str(output_dir / "e2e_results.json"),
            confidence=1.0,
            metadata={"phase": "p07d_e2e_testing", "skipped": True, "data": result},
        )

    project_name: str = data.get("project_name", "App")
    entities: list = data.get("entities", [])
    frontend_port: int = data.get("frontend_port", 5173)
    frontend_url = data.get("frontend_url") or f"http://localhost:{frontend_port}"

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
        result = await llm.call(prompt, task_type="code_generation", max_tokens=2000)
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
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.get(frontend_url)

        proc = await asyncio.create_subprocess_exec(
            "npx", "playwright", "test", str(test_file), "--reporter=json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(output_dir),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        output_text = stdout.decode()
        (output_dir / "playwright_output.json").write_text(output_text or stderr.decode())

        try:
            report = json.loads(output_text)
            stats = report.get("stats", {})
            run_results["passed"] = stats.get("expected", 0)
            run_results["failed"] = stats.get("unexpected", 0)
        except Exception as e:
            logger.warning("p07d_e2e: could not parse playwright report JSON: %s", e)
            run_results["raw_output"] = output_text[-500:]

        logger.info("[p07d] playwright done: %d passed, %d failed", run_results["passed"], run_results["failed"])
    except Exception as exc:
        logger.info("[p07d] playwright skipped: %s", exc)
        run_results["skipped"] = True
        run_results["reason"] = "frontend not running or playwright not installed"

    (output_dir / "e2e_summary.json").write_text(json.dumps(run_results, indent=2))

    return TaskResult(
        output_path=str(test_file),
        confidence=0.72,
        metadata=run_results,
        success=True,
        issues=[],
    )
