"""Helpers for p00c architecture planner — validation and fallback generation."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_VALID_COMMS = {"rest", "grpc", "event"}
_VALID_LANGS = {"go", "python", "typescript", "java"}
_VALID_BUS = {"", "kafka", "rabbitmq", "redis_streams"}

FRAMEWORK_FOR_LANG: Dict[str, str] = {
    "go": "gin",
    "python": "fastapi",
    "typescript": "fastify",
    "java": "spring_boot",
}


def validate_service_map(raw: Dict[str, Any]) -> List[str]:
    """Return a list of validation error strings (empty = valid)."""
    errors: List[str] = []
    services = raw.get("services")
    if not isinstance(services, list) or not services:
        errors.append("services must be a non-empty list")
        return errors

    seen_ports: set = set()
    for i, svc in enumerate(services):
        tag = f"services[{i}] ({svc.get('name', '?')})"
        if not svc.get("name"):
            errors.append(f"{tag}: missing name")
        if svc.get("lang") not in _VALID_LANGS:
            errors.append(f"{tag}: invalid lang {svc.get('lang')!r}")
        if svc.get("communication") not in _VALID_COMMS:
            errors.append(f"{tag}: invalid communication {svc.get('communication')!r}")
        port = svc.get("port")
        if not isinstance(port, int) or port < 1024:
            errors.append(f"{tag}: port must be an integer >= 1024")
        elif port in seen_ports:
            errors.append(f"{tag}: duplicate port {port}")
        else:
            seen_ports.add(port)

    if raw.get("message_bus") not in _VALID_BUS:
        errors.append(f"message_bus {raw.get('message_bus')!r} is not valid")

    return errors


def build_fallback_service_map(
    spec_text: str,
    domain: str,
    backend_lang: str,
    backend_framework: str,
) -> Dict[str, Any]:
    """
    Minimal two-service map used when the LLM fails or returns invalid JSON.
    Keeps the pipeline alive — downstream generators still produce real code.
    """
    fw = backend_framework or FRAMEWORK_FOR_LANG.get(backend_lang, "fastapi")
    return {
        "services": [
            {
                "name": "auth-service",
                "description": "User authentication and JWT issuance",
                "lang": backend_lang,
                "framework": fw,
                "port": 8001,
                "owns_entities": ["User", "Session"],
                "communication": "rest",
                "db": "postgres",
                "critical": True,
            },
            {
                "name": "app-service",
                "description": f"Core {domain} business logic and data APIs",
                "lang": backend_lang,
                "framework": fw,
                "port": 8002,
                "owns_entities": [],
                "communication": "rest",
                "db": "postgres",
                "critical": True,
            },
        ],
        "message_bus": "",
        "api_gateway": "nginx",
        "shared_db": False,
        "notes": "Fallback minimal architecture — LLM classification failed",
        "_fallback": True,
    }


def normalise_service_map(raw: Dict[str, Any], backend_lang: str) -> Dict[str, Any]:
    """Fill in missing fields on each service with sensible defaults."""
    for svc in raw.get("services", []):
        if not svc.get("framework"):
            svc["framework"] = FRAMEWORK_FOR_LANG.get(svc.get("lang", backend_lang), "fastapi")
        if not svc.get("owns_entities"):
            svc["owns_entities"] = []
        if not svc.get("db"):
            svc["db"] = "postgres"
        if "critical" not in svc:
            svc["critical"] = True
    return raw
