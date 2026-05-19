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

    async def _check_docker(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "info",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)
            return proc.returncode == 0
        except Exception:
            return False

    async def run(self, phase_input: Any) -> Dict[str, Any]:
        docker_available = await self._check_docker()
        if not docker_available:
            run_id: str = getattr(phase_input, "run_id", "unknown")
            project_dir = Path(os.path.expanduser(
                f"~/.aether_os/projects/{run_id}"
            ))
            instructions_dir = project_dir / "p11_deployment"
            instructions_dir.mkdir(parents=True, exist_ok=True)
            instructions_path = instructions_dir / "deployment_instructions.md"
            compose_path = project_dir / "docker-compose.yml"
            instructions_path.write_text(
                f"# Deployment Instructions\n\n"
                f"Docker is not available in the current environment.\n\n"
                f"## Manual Deployment\n\n"
                f"Deploy manually with:\n\n"
                f"```bash\ncd {project_dir}\ndocker-compose up --build\n```\n\n"
                f"Or build and run the Docker image directly:\n\n"
                f"```bash\ncd {project_dir}\ndocker build -t aetheros-app .\n"
                f"docker run -p 8000:8000 aetheros-app\n```\n\n"
                f"The application will be available at http://localhost:8000\n"
            )
            # Always write docker-compose.yml and DEPLOY.md even when Docker is absent
            self._write_docker_compose(project_dir, project_dir)
            self._write_deploy_md(project_dir)
            return {
                "success": True,
                "skipped": True,
                "output_path": str(instructions_path),
                "message": f"Docker not available. Deploy manually with: `docker-compose up --build` in {project_dir}",
                "live_url": None,
            }

        run_id: str = phase_input.run_id
        project_dir = Path(os.path.expanduser(
            f"~/.aether_os/projects/{run_id}"
        ))

        main_py = self._find_main_py(project_dir)
        if not main_py:
            # Generate fallback app directly from requirement
            raw_input = getattr(phase_input, "raw_input", "") or (
                getattr(phase_input, "input_data", {}) or {}
            ).get("raw_input", "")
            if raw_input:
                main_py = self._generate_fallback_app(project_dir, raw_input)
            if not main_py:
                return {
                    "success": False,
                    "error": "No main.py found to deploy",
                    "skipped": True,
                }

        # If the found main.py is a stub, generate the real app beside it
        if not self._is_real_app(main_py):
            raw_input = getattr(phase_input, "raw_input", "") or (
                getattr(phase_input, "input_data", {}) or {}
            ).get("raw_input", "")
            if raw_input:
                fallback_py = self._generate_fallback_app(
                    main_py.parent, raw_input, dest=main_py
                )
                if fallback_py:
                    main_py = fallback_py

        app_dir = main_py.parent
        self._write_dockerfile(app_dir, main_py)
        self._write_docker_compose(project_dir, app_dir)
        self._write_deploy_md(project_dir)

        port = self._find_free_port()
        image_name = f"aetheros-{run_id[:8]}"
        container_name = f"aetheros-app-{run_id[:8]}"

        # Remove any stale container from a previous run
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
        )

        await self._ensure_network()

        build_result = await self._docker_build(app_dir, image_name)
        if not build_result["success"]:
            return build_result

        run_result = await self._docker_run(image_name, container_name, port, run_id)
        if not run_result["success"]:
            return run_result

        ready = await self._wait_for_ready(port, timeout=30)
        # Use PUBLIC_HOST env var so the URL is externally accessible on a VPS.
        # Falls back to localhost for local dev.
        public_host = os.environ.get("PUBLIC_HOST", "localhost")
        live_url = f"http://{public_host}:{port}"

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

    def _is_real_app(self, path: Path) -> bool:
        """True only if the file looks like a real generated app, not a stub."""
        try:
            content = path.read_text()
            return (
                "FastAPI" in content
                and len(content) > 500
                and "@app." in content
                and content.count("@app.") >= 1   # at least one route (including /health)
            )
        except Exception:
            return False

    def _find_main_py(self, project_dir: Path) -> Optional[Path]:
        """
        Find the real main.py with priority order.
        Skips scaffolding stubs (< 500 bytes or only /health).
        """
        # Priority 1: backend codegen output
        priority_candidates = [
            project_dir / "src" / "main.py",
            project_dir / "p04_backend" / "src" / "main.py",
            project_dir / "p04_backend" / "backend_codegen" / "src" / "main.py",
            project_dir / "p04a_backend_codegen" / "src" / "main.py",
        ]
        for c in priority_candidates:
            if c.exists() and self._is_real_app(c):
                return c

        # Priority 2: any main.py that looks like a real app
        for found in sorted(project_dir.rglob("main.py")):
            if self._is_real_app(found):
                return found

        # Last resort: any main.py (including scaffolding stub)
        found_all = list(project_dir.rglob("main.py"))
        return found_all[0] if found_all else None

    def _generate_fallback_app(
        self,
        target_dir: Path,
        raw_input: str,
        dest: Optional[Path] = None,
    ) -> Optional[Path]:
        """
        Generate a domain-specific app from raw_input when p04_backend timed out.
        Writes to dest (or target_dir/main.py) and returns the path.
        """
        try:
            # Import domain templates from p04a
            import sys, importlib.util
            ta_path = Path(__file__).parent.parent / "p04a_backend_codegen" / "task_agent.py"
            if not ta_path.exists():
                return None
            # Load the module without triggering package __init__
            import types, builtins

            real_import = builtins.__import__

            def _stub_import(name, *args, **kwargs):
                if "aether_os" in name:
                    m = sys.modules.get(name)
                    if m is None:
                        m = types.ModuleType(name)
                        sys.modules[name] = m
                    return m
                return real_import(name, *args, **kwargs)

            builtins.__import__ = _stub_import
            try:
                spec = importlib.util.spec_from_file_location("_p04a_ta", ta_path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            finally:
                builtins.__import__ = real_import

            code = mod._generate_from_requirement(raw_input)
            import ast
            ast.parse(code)  # validate

            if dest is None:
                dest = target_dir / "main.py"
            dest.write_text(code)

            # Also write httpx to requirements.txt if missing
            req = dest.parent / "requirements.txt"
            if req.exists():
                if "httpx" not in req.read_text():
                    req.write_text(req.read_text() + "\nhttpx>=0.27.0\n")
            else:
                req.write_text(
                    "fastapi>=0.111.0\nuvicorn[standard]>=0.29.0\n"
                    "pydantic>=2.0.0\nhttpx>=0.27.0\npython-dotenv\n"
                )
            return dest
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "[p11] fallback app generation failed: %s", exc
            )
            return None

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
            RUN pip install --no-cache-dir \\
                fastapi uvicorn pydantic \\
                python-jose passlib bcrypt \\
                python-multipart aiofiles \\
                sentry-sdk[fastapi] sqlalchemy \\
                prometheus-client httpx requests \\
                python-dotenv 2>/dev/null || true
            RUN useradd -u 1001 -r -s /sbin/nologin appuser && chown -R appuser /app
            USER 1001
            EXPOSE 8000
            CMD ["uvicorn", "{module_path}:app", \\
                "--host", "0.0.0.0", "--port", "8000"]
        """).strip()

        dockerfile_path = app_dir / "Dockerfile"
        dockerfile_path.write_text(content)
        return dockerfile_path

    def _write_docker_compose(
        self, project_dir: Path, app_dir: Path
    ) -> Path:
        """Write a docker-compose.yml to the project root.

        If a valid docker-compose.yml already exists at the project root it is
        left unchanged.  If one exists but cannot be parsed (broken YAML), it is
        replaced with this safe default.
        """
        compose_path = project_dir / "docker-compose.yml"
        if compose_path.exists():
            try:
                import yaml  # type: ignore[import]
                yaml.safe_load(compose_path.read_text())
                return compose_path  # existing file is valid — leave it
            except Exception:
                pass  # fall through to overwrite with the safe default

        # Determine the relative build context (app_dir relative to project_dir)
        try:
            build_ctx = str(app_dir.relative_to(project_dir))
        except ValueError:
            build_ctx = "."

        content = textwrap.dedent(f"""\
            version: '3.8'
            services:
              api:
                build: {build_ctx}
                environment:
                  DATABASE_URL: ${{DATABASE_URL:-sqlite+aiosqlite:///./data/app.db}}
                  SECRET_KEY: ${{SECRET_KEY:-changeme-in-production-set-64-char-hex}}
                ports:
                  - "8000:8000"
                volumes:
                  - app_data:/app/data
                healthcheck:
                  test: ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
                  interval: 10s
                  timeout: 5s
                  retries: 5

            volumes:
              app_data:
        """)
        compose_path.write_text(content)
        return compose_path

    def _write_deploy_md(self, project_dir: Path) -> Path:
        """Write DEPLOY.md with deployment instructions for Docker, Railway, and Fly.io."""
        deploy_md = project_dir / "DEPLOY.md"
        if deploy_md.exists():
            return deploy_md  # don't overwrite existing guide

        content = textwrap.dedent("""\
            # Deployment Guide

            ## Option 1: Docker Compose (Recommended)

            ```bash
            # Start the app
            docker-compose up --build

            # App will be available at http://localhost:8000
            # API docs at http://localhost:8000/docs
            ```

            ## Option 2: Railway (Cloud)

            1. Install Railway CLI: `npm install -g @railway/cli`
            2. Login: `railway login`
            3. Deploy: `railway up`

            Or deploy via GitHub:
            1. Push this code to a GitHub repo
            2. Go to railway.app → New Project → Deploy from GitHub
            3. Set environment variables: `DATABASE_URL`, `SECRET_KEY`

            ## Option 3: Fly.io

            ```bash
            fly launch
            fly deploy
            ```

            ## Option 4: GitHub Codespaces (instant cloud dev environment)

            1. Push this code to GitHub (the "Push to GitHub" button in the AetherOS dashboard does this)
            2. Click: **[Open in GitHub Codespaces](https://github.com/codespaces/new)**
            3. Everything installs automatically — Python, Node, Docker-in-Docker
            4. The API starts automatically on port 8000

            ## Environment Variables

            See `.env.example` for required configuration.

            ## Production Checklist

            - [ ] Set `SECRET_KEY` to a random 64-character hex string
            - [ ] Configure `DATABASE_URL` for PostgreSQL (recommended for production)
            - [ ] Set `CORS_ORIGINS` to your frontend domain
            - [ ] Enable HTTPS (Railway/Fly handle this automatically)
        """)
        deploy_md.write_text(content)
        return deploy_md

    async def _deploy_to_railway(
        self, project_dir: Path, run_id: str
    ) -> Dict[str, Any]:
        """Attempt to deploy to Railway if RAILWAY_TOKEN is set.

        Returns a status dict.  Always succeeds (best-effort) — callers should
        treat Railway deployment as an optional enhancement, never a hard
        requirement.
        """
        import os
        token = os.environ.get("RAILWAY_TOKEN")
        if not token:
            return {"railway": False, "reason": "RAILWAY_TOKEN not set"}

        try:
            import httpx
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            # Railway GraphQL endpoint
            query = """
            mutation serviceCreate($input: ServiceCreateInput!) {
              serviceCreate(input: $input) { id name }
            }
            """
            # Placeholder: a real deployment requires knowing the Railway project_id
            # and environment_id which must be created first.  The recommended path
            # for automated deployments is via the Railway GitHub integration.
            # We log helpful guidance and return a soft-fail.
            import logging
            logging.getLogger(__name__).info(
                "[p11] Railway automatic deployment requires a pre-created Railway "
                "project.  See DEPLOY.md for instructions."
            )
            return {
                "railway": False,
                "reason": (
                    "Railway deployment requires manual setup — "
                    "see https://railway.app/new or DEPLOY.md"
                ),
            }
        except Exception as exc:
            return {"railway": False, "reason": str(exc)}

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

    async def _ensure_network(self) -> None:
        """Create the aetheros-isolated bridge network if it doesn't exist."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "network", "inspect", "aetheros-isolated",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode != 0:
                create = await asyncio.create_subprocess_exec(
                    "docker", "network", "create",
                    "--driver", "bridge",
                    "--internal",
                    "aetheros-isolated",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(create.communicate(), timeout=15)
        except Exception:
            pass

    async def _docker_run(
        self, image_name: str, container_name: str, port: int, run_id: str = ""
    ) -> Dict[str, Any]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "run", "-d",
                "--name", container_name,
                # D7: bind only to loopback; reverse proxy exposes externally
                "-p", f"127.0.0.1:{port}:8000",
                "--restart", "unless-stopped",
                # D7: network isolation
                "--network", "aetheros-isolated",
                # D7: non-root
                "--user", "1001:1001",
                # D7: read-only root filesystem, writable /tmp only
                "--read-only",
                "--tmpfs", "/tmp:size=64m,mode=1777",
                # D7: resource limits
                "--memory", "512m",
                "--cpus", "0.5",
                # D7: capability hardening
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                # label for cleanup cron
                "--label", f"aetheros.run={run_id or 'unknown'}",
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
