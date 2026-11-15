"""P11 Deployment — file writers.

Contains all template-based file generation: Dockerfile, docker-compose,
Kubernetes manifests, VPS scripts, nginx config, and DEPLOYMENT.md.
"""
from __future__ import annotations
import logging
import os
import re
import shutil
import textwrap
from pathlib import Path

logger = logging.getLogger(__name__)


def write_dockerfile(app_dir: Path, main_py: Path) -> Path:
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
        ENV PYTHONPATH=/app
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


def write_docker_compose(project_dir: Path, app_dir: Path) -> Path:
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
        except Exception as exc:
            logger.debug("p11 writers: docker-compose.yml parse failed, regenerating (non-fatal): %s", exc)

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
              REDIS_URL: ${{REDIS_URL:-redis://redis:6379}}
            ports:
              - "8000:8000"
            volumes:
              - app_data:/app/data
            depends_on:
              redis:
                condition: service_healthy
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

          redis:
            image: redis:7-alpine
            restart: unless-stopped
            healthcheck:
              test: ["CMD", "redis-cli", "ping"]
              interval: 10s
              timeout: 3s
              retries: 3
            deploy:
              resources:
                limits:
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


def write_k8s_manifests(project_dir: Path, app_name: str) -> None:
    """Generate production-grade Kubernetes manifests: HPA, Deployment, Service, Ingress."""
    k8s_dir = project_dir / "k8s"
    k8s_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9-]", "-", app_name.lower()).strip("-") or "app"

    # HPA — targets cpu 70% / memory 80%; min 2 replicas so zero-downtime deploys work
    (k8s_dir / "hpa.yaml").write_text(textwrap.dedent(f"""\
        apiVersion: autoscaling/v2
        kind: HorizontalPodAutoscaler
        metadata:
          name: {slug}-hpa
          namespace: default
        spec:
          scaleTargetRef:
            apiVersion: apps/v1
            kind: Deployment
            name: {slug}
          minReplicas: 2
          maxReplicas: 10
          metrics:
          - type: Resource
            resource:
              name: cpu
              target:
                type: Utilization
                averageUtilization: 70
          - type: Resource
            resource:
              name: memory
              target:
                type: Utilization
                averageUtilization: 80
    """))

    # Deployment
    (k8s_dir / "deployment.yaml").write_text(textwrap.dedent(f"""\
        apiVersion: apps/v1
        kind: Deployment
        metadata:
          name: {slug}
          namespace: default
          labels:
            app: {slug}
        spec:
          replicas: 2
          selector:
            matchLabels:
              app: {slug}
          template:
            metadata:
              labels:
                app: {slug}
            spec:
              securityContext:
                runAsNonRoot: true
                runAsUser: 1000
                fsGroup: 1000
              containers:
              - name: {slug}
                image: {slug}:latest
                ports:
                - containerPort: 8000
                envFrom:
                - secretRef:
                    name: {slug}-secrets
                securityContext:
                  allowPrivilegeEscalation: false
                resources:
                  requests:
                    cpu: "250m"
                    memory: "256Mi"
                  limits:
                    cpu: "1000m"
                    memory: "1Gi"
                livenessProbe:
                  httpGet:
                    path: /health
                    port: 8000
                  initialDelaySeconds: 15
                  periodSeconds: 10
                readinessProbe:
                  httpGet:
                    path: /ready
                    port: 8000
                  initialDelaySeconds: 5
                  periodSeconds: 5
    """))

    # Service
    (k8s_dir / "service.yaml").write_text(textwrap.dedent(f"""\
        apiVersion: v1
        kind: Service
        metadata:
          name: {slug}
          namespace: default
        spec:
          selector:
            app: {slug}
          ports:
          - protocol: TCP
            port: 80
            targetPort: 8000
          type: ClusterIP
    """))

    # Ingress
    (k8s_dir / "ingress.yaml").write_text(textwrap.dedent(f"""\
        apiVersion: networking.k8s.io/v1
        kind: Ingress
        metadata:
          name: {slug}-ingress
          namespace: default
          annotations:
            nginx.ingress.kubernetes.io/rewrite-target: /
            cert-manager.io/cluster-issuer: letsencrypt-prod
        spec:
          tls:
          - hosts:
            - app.yourdomain.com
            secretName: {slug}-tls
          rules:
          - host: app.yourdomain.com
            http:
              paths:
              - path: /
                pathType: Prefix
                backend:
                  service:
                    name: {slug}
                    port:
                      number: 80
    """))

    # Secrets template
    (k8s_dir / "secrets.yaml.template").write_text(textwrap.dedent(f"""\
        # Fill in values and apply: kubectl apply -f k8s/secrets.yaml
        # DO NOT commit this file with real values.
        apiVersion: v1
        kind: Secret
        metadata:
          name: {slug}-secrets
          namespace: default
        type: Opaque
        stringData:
          DATABASE_URL: "postgresql+asyncpg://user:pass@postgres:5432/appdb"
          SECRET_KEY: "replace-with-64-char-hex"
          REDIS_URL: "redis://redis:6379"
    """))

    logger.info("p11: K8s manifests written to %s", k8s_dir)


def write_vps_scripts(project_dir: Path, project_name: str) -> None:
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
    update_sh = """#!/bin/bash
set -e
git pull
docker-compose build
docker-compose up -d
docker-compose exec -T app alembic upgrade head
echo "Update successful."
"""
    (project_dir / "update.sh").write_text(update_sh)
    os.chmod(project_dir / "update.sh", 0o755)


def write_nginx_config(project_dir: Path) -> None:
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


def write_deploy_md(project_dir: Path) -> Path:
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
