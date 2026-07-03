"""P11 Deployment — helper utilities.

Contains: app detection, port allocation, fallback app generation,
cloud deploy utilities (ECS, Cloud Run, Railway), and Docker async helpers.

File writers (Dockerfile, docker-compose, K8s, VPS scripts, nginx, DEPLOYMENT.md)
live in writers.py.
"""
from __future__ import annotations
import asyncio
import builtins
import importlib.util
import json
import logging
import os
import random
import socket
import subprocess
import sys
import types
from pathlib import Path
from typing import Any, Dict, Optional

# Re-export writers so callers can import everything from helpers
from .writers import (  # noqa: F401
    write_dockerfile,
    write_docker_compose,
    write_k8s_manifests,
    write_vps_scripts,
    write_nginx_config,
    write_deploy_md,
)

logger = logging.getLogger(__name__)

_PORT_LOCK_DIR = Path("/tmp/aetheros_port_locks")


# ── App detection ─────────────────────────────────────────────────────────────

def is_real_app(path: Path) -> bool:
    """True only if the file looks like a real generated app, not a stub."""
    try:
        content = path.read_text()
        return (
            "FastAPI" in content
            and len(content) > 500
            and "@app." in content
            and content.count("@app.") >= 1   # at least one route (including /health)
        )
    except Exception as e:
        logger.warning("p11_deployment helpers: _is_real_main_py failed for %s: %s", path, e)
        return False


def find_main_py(project_dir: Path, canonical_src_dir: Optional[str] = None) -> Optional[Path]:
    """
    Find the real main.py with priority order.
    Skips scaffolding stubs (< 500 bytes or only /health).
    P72: canonical_src_dir from pipeline context takes priority so p11 deploys
    from the same directory that p09_observability patched.
    """
    # Priority 0: canonical_src_dir from pipeline context (P72 fix)
    if canonical_src_dir:
        _canon = Path(canonical_src_dir)
        _canon_main = _canon / "main.py"
        if _canon_main.exists() and is_real_app(_canon_main):
            return _canon_main

    # Priority 1: backend codegen output
    priority_candidates = [
        project_dir / "src" / "main.py",
        project_dir / "p04_backend" / "src" / "main.py",
        project_dir / "p04_backend" / "backend_codegen" / "src" / "main.py",
        project_dir / "p04a_backend_codegen" / "src" / "main.py",
    ]
    for c in priority_candidates:
        if c.exists() and is_real_app(c):
            return c

    # Priority 2: any main.py that looks like a real app
    for found in sorted(project_dir.rglob("main.py")):
        if is_real_app(found):
            return found

    # Last resort: any main.py (including scaffolding stub)
    found_all = list(project_dir.rglob("main.py"))
    return found_all[0] if found_all else None


def generate_fallback_app(
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
        ta_path = Path(__file__).parent.parent / "p04a_backend_codegen" / "task_agent.py"
        if not ta_path.exists():
            return None
        # Load the module without triggering package __init__
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

        import ast
        code = mod._generate_from_requirement(raw_input)
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
        logger.warning("[p11] fallback app generation failed: %s", exc)
        return None


# ── Port allocation ───────────────────────────────────────────────────────────

def find_free_port() -> int:
    """
    Find a free port using PID-file locking to prevent collisions between
    concurrent pipeline runs. Randomises the search order so sequential
    runs don't always race for port 8200.
    """
    _PORT_LOCK_DIR.mkdir(parents=True, exist_ok=True)
    candidates = list(range(8200, 8900))
    random.shuffle(candidates)

    for port in candidates:
        lock_file = _PORT_LOCK_DIR / f"{port}.pid"

        # If a lock file exists, check whether the owning PID is still alive
        if lock_file.exists():
            try:
                pid = int(lock_file.read_text().strip())
                os.kill(pid, 0)   # raises if PID dead
                continue          # port claimed by a live process
            except (ValueError, OSError):
                lock_file.unlink(missing_ok=True)   # stale lock — clear it

        # Verify the port is actually free at the OS level
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue

        # Atomically claim the port
        try:
            lock_file.write_text(str(os.getpid()))
            return port
        except OSError:
            continue

    # Fallback: sequential scan (should not be reached in practice)
    for port in range(8100, 8200):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("", port))
                return port
            except OSError:
                continue
    return 8100


# ── Cloud deploy helpers ──────────────────────────────────────────────────────

async def deploy_to_aws_ecs(project_dir: Path, run_id: str) -> Dict[str, Any]:
    """
    Deploy generated Docker container to AWS ECS Fargate.
    Requires: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION env vars.
    """
    key = os.environ.get("AWS_ACCESS_KEY_ID")
    secret = os.environ.get("AWS_SECRET_ACCESS_KEY")
    region = os.environ.get("AWS_REGION", "us-east-1")
    ecr_repo = os.environ.get("AWS_ECR_REPO", "")
    ecs_cluster = os.environ.get("AWS_ECS_CLUSTER", "")

    if not all([key, secret, ecr_repo, ecs_cluster]):
        return {
            "aws_ecs": False,
            "reason": (
                "Set AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_ECR_REPO, "
                "AWS_ECS_CLUSTER to deploy to ECS"
            ),
            "guide": "See DEPLOY.md -> Option 5: AWS ECS Fargate",
        }

    try:
        import boto3  # type: ignore
        session = boto3.Session(
            aws_access_key_id=key,
            aws_secret_access_key=secret,
            region_name=region,
        )
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        account_id = identity["Account"]
        ecr_image_uri = (
            f"{account_id}.dkr.ecr.{region}.amazonaws.com/{ecr_repo}:latest"
        )
        logger.info(
            "[p11] AWS ECS deployment: build image %s and update cluster %s.",
            ecr_image_uri, ecs_cluster,
        )
        return {
            "aws_ecs": True,
            "ecr_image": ecr_image_uri,
            "cluster": ecs_cluster,
            "account": account_id,
            "next_step": (
                f"docker build -t {ecr_image_uri} {project_dir} && "
                f"docker push {ecr_image_uri} && "
                f"aws ecs update-service --cluster {ecs_cluster} "
                f"--service {ecr_repo} --force-new-deployment"
            ),
        }
    except Exception as exc:
        logger.warning("p11_deployment: deploy_to_aws_ecs failed: %s", exc)
        return {"aws_ecs": False, "reason": str(exc)}


async def deploy_to_cloud_run(project_dir: Path, run_id: str) -> Dict[str, Any]:
    """Deploy generated Docker container to Google Cloud Run."""
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    region = os.environ.get("GOOGLE_CLOUD_REGION", "us-central1")

    if not project:
        return {
            "cloud_run": False,
            "reason": "Set GOOGLE_CLOUD_PROJECT to deploy to Cloud Run",
            "guide": "See DEPLOY.md -> Option 6: Google Cloud Run",
        }

    service_name = f"aetheros-{run_id[:8]}"
    image = f"gcr.io/{project}/{service_name}:latest"

    return {
        "cloud_run": True,
        "image": image,
        "service": service_name,
        "region": region,
        "next_step": (
            f"gcloud builds submit --tag {image} {project_dir} && "
            f"gcloud run deploy {service_name} --image {image} "
            f"--region {region} --allow-unauthenticated"
        ),
    }


async def deploy_to_railway(project_dir: Path, run_id: str) -> Dict[str, Any]:
    """Attempt to deploy to Railway if RAILWAY_TOKEN is set (best-effort)."""
    token = os.environ.get("RAILWAY_TOKEN")
    if not token:
        return {"railway": False, "reason": "RAILWAY_TOKEN not set"}

    try:
        railway_config = {
            "$schema": "https://railway.app/railway.schema.json",
            "build": {"builder": "NIXPACKS"},
            "deploy": {"startCommand": "uvicorn main:app --host 0.0.0.0 --port $PORT"},
        }
        (project_dir / "railway.json").write_text(
            json.dumps(railway_config, indent=2)
        )
        result = subprocess.run(
            ["railway", "up", "--detach"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            env={**os.environ, "RAILWAY_TOKEN": token},
        )
        if result.returncode == 0:
            logger.info("[p11] Railway deployment succeeded: %s", result.stdout[:200])
            return {"railway": True, "output": result.stdout, "error": result.stderr}
        else:
            logger.warning("[p11] Railway CLI returned non-zero: %s", result.stderr[:200])
            return {"railway": False, "output": result.stdout, "error": result.stderr}
    except FileNotFoundError:
        return {
            "railway": False,
            "reason": "Railway CLI not installed — install with: npm install -g @railway/cli",
        }
    except Exception as exc:
        logger.warning("p11_deployment: deploy_to_railway failed: %s", exc)
        return {"railway": False, "reason": str(exc)}


# ── Docker low-level helpers ──────────────────────────────────────────────────

async def docker_build(app_dir: Path, image_name: str) -> Dict[str, Any]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "build", "-t", image_name, str(app_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
        if proc.returncode != 0:
            return {
                "success": False,
                "error": f"Docker build failed: {stderr.decode()[:500]}",
            }
        return {"success": True}
    except asyncio.TimeoutError:
        return {"success": False, "error": "Docker build timed out (600s)"}
    except FileNotFoundError:
        return {"success": False, "error": "Docker not found — is Docker installed?"}
    except Exception as exc:
        logger.warning("p11_deployment: docker_build failed: %s", exc)
        return {"success": False, "error": str(exc)}


async def ensure_network() -> None:
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
    except Exception as exc:
        logger.warning("[p11] ensure_network failed (non-fatal): %s", exc)


async def docker_run(
    image_name: str, container_name: str, port: int, run_id: str = ""
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
            # D7: read-only root filesystem; tmpfs for /tmp and /app/data (SQLite writes)
            "--read-only",
            "--tmpfs", "/tmp:size=64m,mode=1777",
            "--tmpfs", "/app/data:size=256m,uid=1001,gid=1001",
            # Redirect SQLite DB into the writable /app/data tmpfs mount so
            # --read-only doesn't break apps that default to ./app.db
            "-e", "DATABASE_URL=sqlite+aiosqlite:////app/data/app.db",
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
        logger.warning("p11_deployment: docker_run failed: %s", exc)
        return {"success": False, "error": str(exc)}


async def wait_for_ready(port: int, timeout: int = 30) -> bool:
    """Poll /health until the container responds or we time out."""
    try:
        import aiohttp
        url = f"http://localhost:{port}/health"
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                        if resp.status < 500:
                            return True
            except Exception as exc:
                logger.debug("p11 helpers: health probe attempt failed (retrying): %s", exc)
            await asyncio.sleep(2)
    except ImportError:
        # aiohttp not available — just wait a fixed time
        await asyncio.sleep(5)
    return False
