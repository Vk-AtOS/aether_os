"""
G7: Architecture diagram parser for P00a multimodal intake.

Sends an image (base64-encoded or file path) to Claude Vision and extracts
a service graph with service boxes, databases, queues, and connections.

Public API:
    parse_diagram(image_path: str, anthropic_client=None) -> dict
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DIAGRAM_EXTRACTION_PROMPT = """\
This is a software architecture diagram. Extract the following and return as JSON ONLY (no prose):

{
  "services": [
    {"name": "ServiceName", "type": "api|web|worker|gateway|auth", "description": "what it does"}
  ],
  "databases": [
    {"name": "DbName", "type": "postgres|mysql|mongodb|redis|elasticsearch|kafka|s3"}
  ],
  "queues": [
    {"name": "QueueName", "type": "kafka|rabbitmq|sqs|redis_streams"}
  ],
  "connections": [
    {"from": "ServiceA", "to": "ServiceB", "protocol": "REST|gRPC|async|SQL"}
  ],
  "external_apis": [
    {"name": "APIName", "purpose": "what it provides"}
  ],
  "inferred_domain": "healthcare|fintech|ecommerce|hrm|education|general"
}

If you cannot identify something, use an empty list. Do not invent components that are not visible.
"""


def parse_diagram(image_path: str, anthropic_client: Optional[Any] = None) -> dict:
    """
    Extract a service graph from an architecture diagram image.

    Args:
        image_path: Absolute path to the image file (PNG, JPG, GIF, WEBP).
        anthropic_client: Optional pre-built Anthropic client. If None, uses
            get_llm_client() from aether_os.core.llm.client.

    Returns a dict with keys:
        services, databases, queues, connections, external_apis,
        inferred_domain, raw_spec

    Never raises — logs warnings and returns best-effort output.
    """
    empty_result: dict = {
        "services": [],
        "databases": [],
        "queues": [],
        "connections": [],
        "external_apis": [],
        "inferred_domain": "general",
        "raw_spec": "Architecture diagram could not be parsed — please provide requirements as text.",
    }

    try:
        img_path = Path(image_path)
        if not img_path.exists():
            logger.warning("[p00a_intake] diagram image not found: %s", image_path)
            return empty_result

        image_bytes = img_path.read_bytes()
        # Detect MIME type from extension
        ext = img_path.suffix.lower()
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".gif": "image/gif", ".webp": "image/webp"}
        image_mime = mime_map.get(ext, "image/png")

        if anthropic_client is None:
            try:
                from aether_os.core.llm.client import get_llm_client
                llm = get_llm_client()
            except Exception as exc:
                logger.warning("[p00a_intake] could not get LLM client for diagram: %s", exc)
                return empty_result
        else:
            llm = anthropic_client

        import asyncio

        async def _call() -> str:
            return await llm.call_vision(
                _DIAGRAM_EXTRACTION_PROMPT, image_bytes, task_type="analysis"
            )

        # Handle both sync and async contexts
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    future = ex.submit(asyncio.run, _call())
                    raw = future.result(timeout=60)
            else:
                raw = loop.run_until_complete(_call())
        except Exception as exc:
            logger.warning("[p00a_intake] diagram LLM call failed: %s", exc)
            return empty_result

        # Parse JSON response
        import json
        import re
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # Try extracting JSON from prose
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                except Exception as exc:
                    logger.warning("[p00a_intake] diagram JSON parse failed: %s", exc)
                    return empty_result
            else:
                return empty_result

        # Build plain-English spec from the parsed graph
        services = parsed.get("services", [])
        databases = parsed.get("databases", [])
        queues = parsed.get("queues", [])
        connections = parsed.get("connections", [])
        external_apis = parsed.get("external_apis", [])
        domain = parsed.get("inferred_domain", "general")

        spec_parts = []
        if services:
            spec_parts.append(
                f"Services: {', '.join(s['name'] for s in services[:8])}."
            )
        if databases:
            spec_parts.append(
                f"Databases: {', '.join(d['name'] for d in databases[:5])}."
            )
        if queues:
            spec_parts.append(
                f"Message queues: {', '.join(q['name'] for q in queues[:4])}."
            )
        if connections:
            conn_str = "; ".join(
                "{} -> {}".format(c.get("from", ""), c.get("to", ""))
                for c in connections[:6]
            )
            spec_parts.append(f"Connections: {conn_str}.")
        if external_apis:
            spec_parts.append(
                f"External integrations: {', '.join(a['name'] for a in external_apis[:5])}."
            )

        return {
            "services": services,
            "databases": databases,
            "queues": queues,
            "connections": connections,
            "external_apis": external_apis,
            "inferred_domain": domain,
            "raw_spec": "Build a system with: " + " ".join(spec_parts) if spec_parts else empty_result["raw_spec"],
        }

    except Exception as exc:
        logger.warning("[p00a_intake] parse_diagram failed: %s", exc)
        return empty_result
