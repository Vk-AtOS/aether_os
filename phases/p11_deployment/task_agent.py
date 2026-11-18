"""
P11 Deployment — TaskAgent

Builds a Docker image from the generated project and runs it on a free
local port.  Returns live_url so the pipeline can store it on the run.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from .helpers import (
    find_main_py,
    find_free_port,
    write_dockerfile,
    write_docker_compose,
    write_k8s_manifests,
    write_vps_scripts,
    write_nginx_config,
    write_deploy_md,
    docker_build,
    docker_run,
    ensure_network,
    wait_for_ready,
)

logger = logging.getLogger(__name__)


def _cleanup_containers(container_name: str) -> None:
    """Remove this run's old container and any crash-looping aetheros-app containers."""
    subprocess.run(["docker", "stop", container_name], capture_output=True, timeout=60)
    subprocess.run(["docker", "rm", container_name], capture_output=True, timeout=60)
    try:
        ps = subprocess.run(
            ["docker", "ps", "-a", "--filter", "name=aetheros-app-", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True, text=True, timeout=30,
        )
        for line in ps.stdout.splitlines():
            parts = line.split("\t", 1)
            if len(parts) != 2 or "Restarting" not in parts[1] or parts[0] == container_name:
                continue
            inspect = subprocess.run(["docker", "inspect", "--format", "{{.RestartCount}}", parts[0]],
                                     capture_output=True, text=True, timeout=30)
            try:
                if int(inspect.stdout.strip()) > 10:
                    subprocess.run(["docker", "rm", "-f", parts[0]], capture_output=True, timeout=60)
                    logger.info("[p11] removed crash-looping container %s", parts[0])
            except ValueError as cleanup_exc:
                logger.warning("[p11] container cleanup failed for %s: %s", parts[0], cleanup_exc)
    except (OSError, subprocess.SubprocessError) as ps_exc:
        logger.warning("[p11] container list check failed (non-fatal): %s", ps_exc)


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
        except Exception as e:
            logger.warning("p11_deployment: docker availability check failed: %s", e)
            return False

    async def run(self, phase_input: Any) -> Dict[str, Any]:
        run_id: str = getattr(phase_input, "run_id", "unknown")
        project_dir = Path(os.path.expanduser(
            f"~/.aether_os/projects/{run_id}"
        ))
        data = getattr(phase_input, "input_data", {}) or {}
        project_name = data.get("project_name", "App")

        write_vps_scripts(project_dir, project_name)
        write_nginx_config(project_dir)
        # Always generate K8s manifests regardless of Docker availability
        try:
            write_k8s_manifests(project_dir, project_name)
        except Exception as k8s_exc:
            logger.warning("p11: K8s manifest generation failed (non-fatal): %s", k8s_exc)

        docker_available = await self._check_docker()
        if not docker_available:
            instructions_dir = project_dir / "p11_deployment"
            instructions_dir.mkdir(parents=True, exist_ok=True)
            instructions_path = instructions_dir / "deployment_instructions.md"
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
            write_docker_compose(project_dir, project_dir)
            write_deploy_md(project_dir)
            return {
                "success": True,
                "skipped": True,
                "output_path": str(instructions_path),
                "message": f"Docker not available. Deploy manually with: `docker-compose up --build` in {project_dir}",
                "live_url": None,
            }

        run_id = phase_input.run_id
        project_dir = Path(os.path.expanduser(
            f"~/.aether_os/projects/{run_id}"
        ))
        # P72: read canonical_src_dir from pipeline context so we deploy from the same
        # directory that p09_observability patched (not a stale scaffolding copy).
        _canonical_src = data.get("canonical_src_dir")

        main_py = find_main_py(project_dir, canonical_src_dir=_canonical_src)
        if not main_py:
            return {
                "success": False,
                "error": "No main.py found to deploy",
                "skipped": True,
            }

        app_dir = main_py.parent
        write_dockerfile(app_dir, main_py)
        write_docker_compose(project_dir, app_dir)
        write_deploy_md(project_dir)

        # FIX 33: Check for frontend build failure
        frontend_build_failed = False
        if hasattr(phase_input, "phase_outputs"):
            for phase_output in phase_input.phase_outputs:
                if phase_output.phase_name == "frontend":
                    frontend_build_failed = phase_output.metadata.get("frontend_build_failed", False)
                    break

        if frontend_build_failed:
            logger.error("p11: Deployment aborted: Frontend build failed.")
            return {
                "success": False,
                "error": "Frontend build failed — see p05 logs. Cannot deploy.",
                "skipped": True,
            }

        port = find_free_port()
        image_name = f"aetheros-{run_id[:8]}"
        container_name = f"aetheros-app-{run_id[:8]}"

        # Blocking docker CLI calls: run them off the event loop.
        await asyncio.to_thread(_cleanup_containers, container_name)

        await ensure_network()

        build_result = await docker_build(app_dir, image_name)
        if not build_result["success"]:
            return build_result

        run_result = await docker_run(image_name, container_name, port, run_id)
        if not run_result["success"]:
            return run_result

        ready = await wait_for_ready(port, timeout=30)

        # Problem 53 & 63: if health check fails, gate must fail — include container logs
        if not ready:
            _container_logs = ""
            try:
                _logs_result = await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "logs", "--tail", "50", container_name],
                    capture_output=True, text=True, timeout=10,
                )
                _container_logs = (_logs_result.stdout + _logs_result.stderr)[-3000:]
            except Exception as log_exc:
                logger.warning("[p11] failed to collect container logs: %s", log_exc)
            deploy_file = project_dir / "p11_deployment" / "deployment.json"
            deploy_file.parent.mkdir(parents=True, exist_ok=True)
            deploy_info_failed: Dict[str, Any] = {
                "live_url": None,
                "port": port,
                "image_name": image_name,
                "container_name": container_name,
                "ready": False,
                "app_dir": str(app_dir),
                "docker_valid": 0,  # Problem 63: 0 when health check fails
                "failure_reason": "Container health check failed — /health did not return HTTP 200 within 30s",
                "container_logs_tail": _container_logs,
            }
            deploy_file.write_text(json.dumps(deploy_info_failed, indent=2))
            return {
                "success": False,
                "ready": False,
                "live_url": None,
                "port": port,
                "container_name": container_name,
                "output_file": str(deploy_file),
                "docker_valid": 0,
                "issues": [
                    "Container health check failed — /health did not return HTTP 200 within 30s",
                    f"Container logs (last 50 lines):\n{_container_logs}",
                ],
            }

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
            "docker_valid": 100,  # Problem 63: 100 only when health check passes
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
            "docker_valid": 100,
            "container_name": container_name,
            "output_file": str(deploy_file),
        }
