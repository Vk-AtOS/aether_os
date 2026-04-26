"""
P11 Deployment — TaskAgent

Builds a Docker image from the generated project and runs it on a free
local port.  Returns live_url so the pipeline can store it on the run.
"""
from __future__ import annotations
import asyncio
import json
import os
import shutil
import socket
import subprocess
import textwrap
from pathlib import Path
from typing import Any, Dict, Optional


class TaskAgent:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    async def run(self, phase_input: Any) -> Dict[str, Any]:
        run_id: str = phase_input.run_id
        project_dir = Path(os.path.expanduser(
            f"~/.aether_os/projects/{run_id}"
        ))

        main_py = self._find_main_py(project_dir)
        if not main_py:
            return {
                "success": False,
                "error": "No main.py found to deploy",
                "skipped": True,
            }

        app_dir = main_py.parent
        self._write_dockerfile(app_dir, main_py)

        port = self._find_free_port()
        image_name = f"aetheros-{run_id[:8]}"
        container_name = f"aetheros-app-{run_id[:8]}"

        # Remove any stale container from a previous run
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
        )

        build_result = await self._docker_build(app_dir, image_name)
        if not build_result["success"]:
            return build_result

        run_result = await self._docker_run(image_name, container_name, port)
        if not run_result["success"]:
            return run_result

        ready = await self._wait_for_ready(port, timeout=30)
        live_url = f"http://localhost:{port}"

        deploy_info: Dict[str, Any] = {
            "live_url": live_url,
            "port": port,
            "image_name": image_name,
            "container_name": container_name,
            "ready": ready,
            "app_dir": str(app_dir),
        }

        deploy_file = project_dir / "p11_deployment" / "deployment.json"
        deploy_file.parent.mkdir(parents=True, exist_ok=True)
        deploy_file.write_text(json.dumps(deploy_info, indent=2))

        return {
            "success": True,
            "live_url": live_url,
            "port": port,
            "ready": ready,
            "container_name": container_name,
            "output_file": str(deploy_file),
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _find_main_py(self, project_dir: Path) -> Optional[Path]:
        """Return the first main.py found, checking canonical locations first."""
        candidates = [
            project_dir / "src" / "main.py",
            project_dir / "p04_backend" / "src" / "main.py",
            project_dir / "p03_scaffolding" / project_dir.name / "main.py",
        ]
        for c in candidates:
            if c.exists():
                return c
        found = list(project_dir.rglob("main.py"))
        return found[0] if found else None

    def _find_free_port(self) -> int:
        for port in range(8100, 8999):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("", port))
                    return port
                except OSError:
                    continue
        return 8100

    def _write_dockerfile(self, app_dir: Path, main_py: Path) -> Path:
        req_file = app_dir / "requirements.txt"
        if not req_file.exists():
            parent_req = app_dir.parent / "requirements.txt"
            if parent_req.exists():
                shutil.copy(parent_req, req_file)

        has_requirements = req_file.exists()
        rel_main = main_py.relative_to(app_dir)
        module_path = str(rel_main).replace("/", ".").replace(".py", "")

        pip_reqs = (
            "RUN pip install --no-cache-dir -r requirements.txt"
            if has_requirements
            else "RUN pip install fastapi uvicorn"
        )

        content = textwrap.dedent(f"""
            FROM python:3.11-slim
            WORKDIR /app
            COPY . .
            {pip_reqs}
            RUN pip install --no-cache-dir fastapi uvicorn \\
                pydantic python-jose passlib bcrypt \\
                python-multipart aiofiles 2>/dev/null || true
            EXPOSE 8000
            CMD ["uvicorn", "{module_path}:app", \\
                "--host", "0.0.0.0", "--port", "8000"]
        """).strip()

        dockerfile_path = app_dir / "Dockerfile"
        dockerfile_path.write_text(content)
        return dockerfile_path

    async def _docker_build(
        self, app_dir: Path, image_name: str
    ) -> Dict[str, Any]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "build", "-t", image_name, str(app_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode != 0:
                return {
                    "success": False,
                    "error": f"Docker build failed: {stderr.decode()[:500]}",
                }
            return {"success": True}
        except asyncio.TimeoutError:
            return {"success": False, "error": "Docker build timed out (120s)"}
        except FileNotFoundError:
            return {"success": False, "error": "Docker not found — is Docker installed?"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _docker_run(
        self, image_name: str, container_name: str, port: int
    ) -> Dict[str, Any]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "run", "-d",
                "--name", container_name,
                "-p", f"{port}:8000",
                "--restart", "unless-stopped",
                image_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode != 0:
                return {
                    "success": False,
                    "error": f"Docker run failed: {stderr.decode()[:300]}",
                }
            return {
                "success": True,
                "container_id": stdout.decode().strip()[:12],
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _wait_for_ready(self, port: int, timeout: int = 30) -> bool:
        """Poll /health until the container responds or we time out."""
        try:
            import aiohttp
            url = f"http://localhost:{port}/health"
            loop = asyncio.get_event_loop()
            deadline = loop.time() + timeout
            while loop.time() < deadline:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                            if resp.status < 500:
                                return True
                except Exception:
                    pass
                await asyncio.sleep(2)
        except ImportError:
            # aiohttp not available — just wait a fixed time
            await asyncio.sleep(5)
        return False
