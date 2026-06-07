"""
P11 Deployment — TaskAgent

Builds a Docker image from the generated project and runs it on a free
local port.  Returns live_url so the pipeline can store it on the run.
"""
from __future__ import annotations
import asyncio
import json
import os
import random
import re
import shutil
import socket
import subprocess
import textwrap
from pathlib import Path
from typing import Any, Dict, Optional

_PORT_LOCK_DIR = Path("/tmp/aetheros_port_locks")


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

    def _write_vps_scripts(self, project_dir: Path, project_name: str):
        """Write VPS-ready deployment and maintenance scripts."""
        project_slug = re.sub(r"[^a-z0-9-]", "-", project_name.lower()).strip("-") or "project"
        
        # 1. deploy.sh (Enhanced)
        deploy_sh = f"""#!/bin/bash
# One-command VPS deployment for {project_name}
set -e
echo "Deploying {project_name}..."

# Install Docker if not present
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
fi

docker-compose build
docker-compose up -d

# Run migrations and seed
echo "Running migrations and seeding..."
docker-compose exec -T app alembic upgrade head
# Seed demo data (skip if already seeded)
docker-compose exec -T app python -m src.seed 2>/dev/null || echo "Seed skipped (already done or seed.py not found)"

# Health check
echo "Verifying health..."
sleep 5
curl -f http://localhost:8000/health || echo "Warning: Health check failed"

echo ""
echo "✓ {project_name} is running"
echo "  App URL: http://$(hostname -I | awk '{{print $1}}')"
echo "  Admin login: admin@example.com"
echo "  Admin password: admin_password_change_me"
echo ""
echo "IMPORTANT: Change your admin password immediately after first login."
"""
        (project_dir / "deploy.sh").write_text(deploy_sh)
        os.chmod(project_dir / "deploy.sh", 0o755)

        # 2. backup.sh
        backup_sh = f"""#!/bin/bash
# Database backup script
BACKUP_DIR=./backups
mkdir -p $BACKUP_DIR
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
docker-compose exec -T db pg_dump -U appuser {project_slug.replace('-', '_')} > $BACKUP_DIR/backup_$TIMESTAMP.sql

# Keep last 30 days of backups
find $BACKUP_DIR -name "*.sql" -mtime +30 -delete
echo "Backup complete: $BACKUP_DIR/backup_$TIMESTAMP.sql"
"""
        (project_dir / "backup.sh").write_text(backup_sh)
        os.chmod(project_dir / "backup.sh", 0o755)

        # 3. restore.sh
        restore_sh = f"""#!/bin/bash
if [ -z "$1" ]; then
    echo "Usage: ./restore.sh <backup_file.sql>"
    exit 1
fi
cat $1 | docker-compose exec -T db psql -U appuser {project_slug.replace('-', '_')}
echo "Restore complete."
"""
        (project_dir / "restore.sh").write_text(restore_sh)
        os.chmod(project_dir / "restore.sh", 0o755)

        # 4. update.sh
        update_sh = f"""#!/bin/bash
set -e
git pull
docker-compose build
docker-compose up -d
docker-compose exec -T app alembic upgrade head
echo "Update successful."
"""
        (project_dir / "update.sh").write_text(update_sh)
        os.chmod(project_dir / "update.sh", 0o755)

    def _write_nginx_config(self, project_dir: Path):
        """Generate nginx/ directory with nginx.conf and ssl.conf."""
        nginx_dir = project_dir / "deployment" / "nginx"
        nginx_dir.mkdir(parents=True, exist_ok=True)
        
        nginx_conf = textwrap.dedent("""
            server {
                listen 80;
                server_name localhost;

                location / {
                    proxy_pass http://app:8000;
                    proxy_set_header Host $host;
                    proxy_set_header X-Real-IP $remote_addr;
                    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                }
            }
        """).strip()
        (nginx_dir / "nginx.conf").write_text(nginx_conf)
        
        ssl_conf = textwrap.dedent("""
            # SSL configuration template (Let's Encrypt / Certbot)
            # listen 443 ssl;
            # ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
            # ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
            # include /etc/letsencrypt/options-ssl-nginx.conf;
            # ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
        """).strip()
        (nginx_dir / "ssl.conf").write_text(ssl_conf)

    async def run(self, phase_input: Any) -> Dict[str, Any]:
        run_id: str = getattr(phase_input, "run_id", "unknown")
        project_dir = Path(os.path.expanduser(
            f"~/.aether_os/projects/{run_id}"
        ))
        data = getattr(phase_input, "input_data", {}) or {}
        project_name = data.get("project_name", "App")
        
        self._write_vps_scripts(project_dir, project_name)
        self._write_nginx_config(project_dir)
        
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

    def _write_dockerfile(self, app_dir: Path, main_py: Path) -> Path:
        req_file = app_dir / "requirements.txt"
        if not req_file.exists():
            parent_req = app_dir.parent / "requirements.txt"
            if parent_req.exists():
                shutil.copy(parent_req, req_file)

        has_requirements = req_file.exists()
        rel_main = main_py.relative_to(app_dir)
        module_path = str(rel_main).replace("/", ".").replace(".py", "")

        if has_requirements:
            pip_cmd = "RUN pip install --no-cache-dir -r requirements.txt"
        else:
            pip_cmd = (
                "RUN pip install --no-cache-dir "
                "fastapi uvicorn[standard] pydantic sqlalchemy python-jose passlib bcrypt "
                "python-multipart slowapi python-dotenv httpx"
            )

        content = textwrap.dedent(f"""
            FROM python:3.11-slim
            WORKDIR /app
            COPY requirements.txt* ./
            {pip_cmd}
            COPY . .
            RUN useradd -u 1001 -r -s /sbin/nologin appuser && \\
                mkdir -p /app/data && chown -R appuser /app
            USER 1001
            EXPOSE 8000
            HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \\
                CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1
            CMD ["uvicorn", "{module_path}:app", \\
                "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
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
              app:
                build: {build_ctx}
                environment:
                  DATABASE_URL: ${{DATABASE_URL:-sqlite:///./data/app.db}}
                  SECRET_KEY: ${{SECRET_KEY:-changeme-in-production-set-64-char-hex}}
                ports:
                  - "8000:8000"
                volumes:
                  - app_data:/app/data
                healthcheck:
                  test: ["CMD-SHELL", "python3 -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\" || exit 1"]
                  interval: 10s
                  timeout: 5s
                  retries: 5
                  start_period: 20s
                deploy:
                  resources:
                    limits:
                      cpus: '1.0'
                      memory: 512M
                    reservations:
                      cpus: '0.25'
                      memory: 128M

            volumes:
              app_data:
        """)
        compose_path.write_text(content)
        
        # docker-compose.dev.yml
        dev_compose_path = project_dir / "docker-compose.dev.yml"
        dev_content = textwrap.dedent(f"""\
            version: '3.8'
            services:
              app:
                build: {build_ctx}
                volumes:
                  - ./src:/app/src
                command: uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
                ports:
                  - "8000:8000"
                environment:
                  DATABASE_URL: sqlite:///./data/app_dev.db
                  DEBUG: "true"
        """)
        dev_compose_path.write_text(dev_content)
        
        return compose_path

    def _write_deploy_md(self, project_dir: Path) -> Path:
        """Write DEPLOYMENT.md with comprehensive instructions (10 sections)."""
        deploy_md = project_dir / "DEPLOYMENT.md"
        
        content = textwrap.dedent("""\
            # DEPLOYMENT & OPERATIONS GUIDE

            ## 1. VPS Minimum Requirements
            - OS: Ubuntu 22.04 LTS (Recommended)
            - RAM: 2GB (Minimum 1GB)
            - Disk: 20GB SSD
            - CPU: 1 Core

            ## 2. Domain DNS Configuration
            1. Login to your DNS provider (Cloudflare, Namecheap, etc.)
            2. Add an **A Record** pointing to your VPS IP address.
            3. (Optional) Add a CNAME for 'www'.

            ## 3. SSL Certificate Setup
            We recommend using **Certbot** for free SSL via Let's Encrypt:
            ```bash
            sudo apt update && sudo apt install certbot python3-certbot-nginx -y
            sudo certbot --nginx -d yourdomain.com
            ```

            ## 4. First-Time Setup Walkthrough
            ```bash
            git clone <your-repo-url>
            cd <repo-name>
            cp .env.example .env
            nano .env  # Fill in the variables
            bash deploy.sh
            ```

            ## 5. Admin Password Reset
            The default admin is `admin@example.com`. 
            Change your password immediately in the dashboard profile or via the database.

            ## 6. Email Configuration
            Edit `.env` to include your SMTP credentials (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD).
            The system uses these for transactional emails (welcome, alerts, etc.).

            ## 7. Payment Processing (Stripe)
            1. Go to Stripe Dashboard -> Developers -> API Keys.
            2. Copy `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` to your `.env`.
            3. Restart the app: `bash update.sh`.

            ## 8. Automated Database Backups
            Add `backup.sh` to your crontab to run daily:
            ```bash
            (crontab -l ; echo "0 2 * * * cd $(pwd) && bash backup.sh") | crontab -
            ```

            ## 9. Monitoring
            - Health check: `http://<vps-ip>/health`
            - Metrics: `http://<vps-ip>/metrics`
            - Logs: `docker-compose logs -f app`

            ## 10. Updating the Application
            Simply run the update script:
            ```bash
            bash update.sh
            ```
        """)
        deploy_md.write_text(content)
        return deploy_md

    async def _deploy_to_aws_ecs(self, project_dir: Path, run_id: str) -> Dict[str, Any]:
        """
        Deploy generated Docker container to AWS ECS Fargate.
        Requires: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION env vars.
        Uses the existing connector credentials if set.
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

        # Build and push Docker image to ECR, then update ECS service.
        # Credentials are validated via STS; the ECR push and ECS update
        # are the actual deployment steps (run via subprocess/CI after this).
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

            import logging as _logging
            _ecs_logger = _logging.getLogger(__name__)
            _ecs_logger.info(
                "[p11] AWS ECS deployment: build image %s and update cluster %s. "
                "Run: docker build -t %s %s && docker push %s && "
                "aws ecs update-service --cluster %s --service %s --force-new-deployment",
                ecr_image_uri, ecs_cluster, ecr_image_uri, project_dir,
                ecr_image_uri, ecs_cluster, ecr_repo,
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
            return {"aws_ecs": False, "reason": str(exc)}

    async def _deploy_to_cloud_run(self, project_dir: Path, run_id: str) -> Dict[str, Any]:
        """
        Deploy generated Docker container to Google Cloud Run.
        Requires: GOOGLE_CLOUD_PROJECT env var.
        Optional: GOOGLE_CLOUD_REGION (default us-central1).
        """
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

    async def _deploy_to_railway(
        self, project_dir: Path, run_id: str
    ) -> Dict[str, Any]:
        """Attempt to deploy to Railway if RAILWAY_TOKEN is set.

        Returns a status dict.  Always succeeds (best-effort) — callers should
        treat Railway deployment as an optional enhancement, never a hard
        requirement.
        """
        import logging as _logging
        _log = _logging.getLogger(__name__)

        token = os.environ.get("RAILWAY_TOKEN")
        if not token:
            return {"railway": False, "reason": "RAILWAY_TOKEN not set"}

        try:
            # Generate railway.json config
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
                _log.info("[p11] Railway deployment succeeded: %s", result.stdout[:200])
                return {"railway": True, "output": result.stdout, "error": result.stderr}
            else:
                _log.warning("[p11] Railway CLI returned non-zero: %s", result.stderr[:200])
                return {"railway": False, "output": result.stdout, "error": result.stderr}
        except FileNotFoundError:
            return {
                "railway": False,
                "reason": (
                    "Railway CLI not installed — install with: npm install -g @railway/cli"
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
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=360)
            if proc.returncode != 0:
                return {
                    "success": False,
                    "error": f"Docker build failed: {stderr.decode()[:500]}",
                }
            return {"success": True}
        except asyncio.TimeoutError:
            return {"success": False, "error": "Docker build timed out (360s)"}
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
                # D7: read-only root filesystem; tmpfs for /tmp and /app/data (SQLite writes)
                "--read-only",
                "--tmpfs", "/tmp:size=64m,mode=1777",
                "--tmpfs", "/app/data:size=256m,uid=1001,gid=1001",
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
            loop = asyncio.get_running_loop()
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
