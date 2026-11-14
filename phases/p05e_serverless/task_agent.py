"""
P05e Serverless — Knative function scaffolding generation.

Activated when build_profile.architecture in ("serverless", "event_driven").
Generates Knative Service manifests, Broker+Trigger YAML, and function handlers
for each domain entity.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.phases.utils import get_domain_ir
from aether_os.phases.p05e_serverless.serverless_generator import generate_serverless_package

logger = logging.getLogger(__name__)

_SERVERLESS_ARCHITECTURES = {"serverless", "event_driven"}


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = phase_input.input_data or {}

    build_profile = data.get("build_profile") or {}
    architecture = build_profile.get("architecture", "monolith")

    if architecture not in _SERVERLESS_ARCHITECTURES:
        logger.info("p05e_serverless: architecture=%s — skipping", architecture)
        return TaskResult(
            output_path=str(output_dir),
            confidence=1.0,
            metadata={"skipped": True, "reason": f"architecture={architecture}"},
            success=True,
        )

    domain_ir = get_domain_ir(data)
    entities = domain_ir.get("entities") or []
    if not entities:
        entities = [{"table": "item", "fields": [{"name": "name", "type": "string"}]}]

    project_name = data.get("project_name") or "app"
    slug = project_name.lower().replace(" ", "-")
    backend_lang = build_profile.get("backend_lang") or build_profile.get("backend_language", "python")

    # Detect AWS Lambda target before generating Knative (GCP) output.
    # Route to AWS when cloud_provider=aws or deployment_target is aws/lambda.
    cloud_provider = data.get("cloud_provider", "gcp").lower()
    deployment_target = data.get("deployment_target", "").lower()
    use_aws_lambda = (
        cloud_provider == "aws"
        or deployment_target in ("aws", "lambda", "aws_lambda")
    )

    if use_aws_lambda:
        # AWS Lambda path — SAM template + Mangum adapter + per-entity handlers
        try:
            from aether_os.phases.p05e_serverless.lambda_generator import (
                gen_sam_template,
                gen_mangum_handler,
                gen_entity_lambda_handler,
                gen_lambda_requirements,
                gen_sam_config,
                gen_lambda_makefile,
                gen_lambda_readme,
            )
            aws_dir = output_dir / "serverless" / "aws"
            aws_src_dir = aws_dir / "src"
            aws_layers_dir = aws_dir / "layers"
            aws_src_dir.mkdir(parents=True, exist_ok=True)
            aws_layers_dir.mkdir(parents=True, exist_ok=True)

            region = data.get("aws_region", "us-east-1")
            (aws_dir / "template.yaml").write_text(
                gen_sam_template(project_name, entities, region)
            )
            (aws_src_dir / "handler.py").write_text(gen_mangum_handler(project_name))
            (aws_dir / "requirements.txt").write_text(gen_lambda_requirements())
            (aws_layers_dir / "requirements.txt").write_text(gen_lambda_requirements())
            (aws_dir / "samconfig.toml").write_text(gen_sam_config(project_name, region))
            (aws_dir / "Makefile").write_text(gen_lambda_makefile(project_name))
            (aws_dir / "README.md").write_text(gen_lambda_readme(project_name, entities))

            # Per-entity Lambda handlers (capped at 8 to stay within Lambda quotas)
            for entity in entities[:8]:
                handler_code = gen_entity_lambda_handler(entity)
                ent_name = entity.get("name", entity.get("table", "item")).lower()
                (aws_src_dir / f"{ent_name}_handler.py").write_text(handler_code)

            fn_count = len(entities[:8]) + 1  # entity handlers + main app
            logger.info(
                "p05e_serverless: AWS Lambda SAM template generated at %s (%d functions)",
                aws_dir, fn_count,
            )
            return TaskResult(
                output_path=str(aws_dir),
                confidence=0.85,
                metadata={
                    "serverless_dir": str(aws_dir),
                    "lambda_template_path": str(aws_dir / "template.yaml"),
                    "function_count": fn_count,
                    "entity_count": len(entities),
                    "cloud_provider": "aws",
                    "region": region,
                },
                success=True,
            )
        except Exception as _aws_exc:
            logger.warning("p05e_serverless: AWS Lambda generation failed (non-fatal): %s", _aws_exc)
            return TaskResult(
                output_path=str(output_dir),
                confidence=0.0,
                metadata={"cloud_provider": "aws", "error": str(_aws_exc)},
                issues=[f"AWS Lambda generation failed: {_aws_exc}"],
                success=False,
            )

    # Existing Knative (GCP) path — unchanged
    try:
        serverless_dir = generate_serverless_package(entities, slug, output_dir, backend_lang)
        fn_count = len(entities) * 3  # created/updated/deleted per entity
        logger.info("p05e_serverless: generated %d functions at %s", fn_count, serverless_dir)
        return TaskResult(
            output_path=str(serverless_dir),
            confidence=0.85,
            metadata={
                "serverless_dir": str(serverless_dir),
                "function_count": fn_count,
                "entity_count": len(entities),
                "backend_lang": backend_lang,
                "cloud_provider": "gcp",
            },
            success=True,
        )
    except Exception as e:
        logger.error("p05e_serverless: generation failed: %s", e)
        return TaskResult(output_path=str(output_dir), confidence=0.0, metadata={}, success=False)
