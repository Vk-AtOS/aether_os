"""P11e Enterprise Deployment — Helm charts, Terraform, and operational scripts.

Generates:
  helm/{app_name}/          — full Helm chart
  helm/kafka/               — Kafka + Zookeeper (microservices / event-driven builds)
  terraform/aws/            — ECS Fargate + RDS + ElastiCache + ALB
  terraform/aws-eks/        — VPC + EKS + RDS + ElastiCache (kubernetes builds)
  terraform/azure/          — AKS + Azure Database + Azure Cache
  .github/workflows/        — CI, deploy, and security scan GitHub Actions
  scripts/                  — backup, restore, upgrade, healthcheck, bundle

Uses template strings for Helm/Terraform/scripts (well-defined artifacts).
Uses one LLM call to customize terraform/aws/main.tf to the specific app.
"""
from __future__ import annotations
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult

from .helpers import write_helm_chart, write_terraform_azure, write_operational_scripts
from .infra_helpers import write_kafka_helm_values, write_github_actions, write_terraform_eks
from .prompts import build_aws_terraform_prompt, aws_terraform_template

logger = logging.getLogger(__name__)


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """Generate Helm charts, Terraform configs, and operational scripts."""
    output_dir.mkdir(parents=True, exist_ok=True)

    data: dict = getattr(phase_input, "input_data", {}) or {}
    project_name = data.get("project_name", "App")
    domain = data.get("domain", "general")
    slug = re.sub(r"[^a-z0-9-]", "-", project_name.lower()).strip("-") or "app"
    raw_input = data.get("raw_input", "")[:2000]

    files_written: List[str] = []

    # ── Template-based artifacts ──────────────────────────────────────────────
    try:
        write_helm_chart(output_dir, project_name, slug)
        files_written.append(f"helm/{slug}/")
    except Exception as exc:
        logger.warning("p11e: Helm chart generation failed: %s", exc)

    try:
        write_terraform_azure(output_dir, project_name, slug)
        files_written.append("terraform/azure/")
    except Exception as exc:
        logger.warning("p11e: Azure Terraform failed: %s", exc)

    try:
        write_operational_scripts(output_dir, project_name, slug)
        files_written.append("scripts/")
    except Exception as exc:
        logger.warning("p11e: operational scripts failed: %s", exc)

    # ── LLM-assisted: Terraform AWS (customized to app) ───────────────────────
    arch = data.get("architecture_json", {})
    tech_stack = arch.get("tech_stack", {}) if isinstance(arch, dict) else {}
    aws_tf_dir = output_dir / "terraform" / "aws"
    aws_tf_dir.mkdir(parents=True, exist_ok=True)

    # Variables and outputs are always template-based
    (aws_tf_dir / "variables.tf").write_text(f"""\
variable "aws_region" {{
  description = "AWS region"
  default     = "us-east-1"
}}

variable "app_name" {{
  description = "Application name"
  default     = "{slug}"
}}

variable "environment" {{
  description = "Deployment environment"
  default     = "production"
}}

variable "db_password" {{
  description = "RDS master password"
  sensitive   = true
}}

variable "container_image" {{
  description = "Docker image URI (ECR)"
  default     = "{slug}:latest"
}}
""")

    (aws_tf_dir / "outputs.tf").write_text("""\
output "alb_dns_name" {
  description = "Application Load Balancer DNS"
  value       = aws_lb.main.dns_name
}

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint"
  value       = aws_db_instance.main.endpoint
}

output "elasticache_endpoint" {
  description = "ElastiCache Redis endpoint"
  value       = aws_elasticache_cluster.main.cache_nodes[0].address
}
""")

    # main.tf — try LLM, fall back to template
    aws_main_tf = aws_terraform_template(slug, project_name, domain)
    try:
        from aether_os.core.llm.client import get_llm_client
        llm = get_llm_client()
        prompt = build_aws_terraform_prompt(project_name, domain, tech_stack, raw_input)
        result = await llm.call(prompt, task_type="code_generation", max_tokens=4000)
        if result and len(result.strip()) > 500:
            result = re.sub(r"^```(?:hcl|terraform)?\s*\n?", "", result.strip())
            result = re.sub(r"\n?```\s*$", "", result.strip())
            aws_main_tf = result
            logger.info("p11e: LLM AWS Terraform generated (%d chars)", len(aws_main_tf))
    except Exception as exc:
        logger.warning("p11e: LLM AWS Terraform failed, using template: %s", exc)

    (aws_tf_dir / "main.tf").write_text(aws_main_tf)
    files_written.append("terraform/aws/")

    # ── Layer 4: Kafka, EKS Terraform, GitHub Actions ─────────────────────────
    build_profile = data.get("build_profile") or {}
    backend_lang = build_profile.get("backend_lang", "python")
    architecture = build_profile.get("architecture", "monolith")
    message_queue = build_profile.get("message_queue", "")
    deployment_target = build_profile.get("deployment_target", "docker_compose")

    is_microservices = architecture == "microservices"
    needs_kafka = message_queue in ("kafka", "rabbitmq")

    if needs_kafka:
        try:
            write_kafka_helm_values(output_dir, slug)
            files_written.append("helm/kafka/")
        except Exception as exc:
            logger.warning("p11e: Kafka Helm values failed: %s", exc)

    if deployment_target == "kubernetes" or is_microservices:
        try:
            write_terraform_eks(output_dir, slug)
            files_written.append("terraform/aws-eks/")
        except Exception as exc:
            logger.warning("p11e: EKS Terraform failed: %s", exc)

    try:
        write_github_actions(output_dir, slug, backend_lang, is_microservices)
        files_written.append(".github/workflows/")
    except Exception as exc:
        logger.warning("p11e: GitHub Actions failed: %s", exc)

    # Write manifest
    manifest: Dict[str, Any] = {
        "phase": "p11e_enterprise_deployment",
        "project_name": project_name,
        "slug": slug,
        "files_written": files_written,
    }
    manifest_path = output_dir / "enterprise_deployment.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    logger.info("p11e: enterprise deployment package complete")

    return TaskResult(
        output_path=str(output_dir),
        confidence=0.9,
        metadata=manifest,
        success=True,
    )
