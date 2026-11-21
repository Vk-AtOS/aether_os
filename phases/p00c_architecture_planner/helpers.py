"""Helpers for p00c architecture planner — validation and fallback generation."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from aether_os.core.llm.json_enforcer import extract_first_json

logger = logging.getLogger(__name__)

_VALID_COMMS = {"rest", "grpc", "event"}
_VALID_LANGS = {"go", "python", "typescript", "java"}
_VALID_BUS = {"", "kafka", "rabbitmq", "redis_streams"}
_FIRST_PORT = 8001
_MAX_NAME_LEN = 64


def _coerce_service(item: Any, backend_lang: str) -> Optional[Dict[str, Any]]:
    """One services[] entry as a dict, or None when it is unusable.

    Real models return entries as objects, as JSON text, or as bare names
    ("auth-service"); the planner used to call .get() on whatever came back.
    """
    if isinstance(item, str):
        text = item.strip()
        if text.startswith("{"):
            try:
                return extract_first_json(text, expect=dict)
            except ValueError as e:
                logger.warning("p00c: service entry is unparseable JSON text, skipped: %s", e)
                return None
        if text and len(text) <= _MAX_NAME_LEN and "\n" not in text:
            # A bare name keeps the model's decomposition; the rest is filled with defaults below.
            return {"name": text, "lang": backend_lang}
        logger.warning("p00c: service entry is free text, skipped: %r", text[:80])
        return None
    if isinstance(item, dict):
        return dict(item)
    logger.warning("p00c: service entry of type %s skipped", type(item).__name__)
    return None


def coerce_service_map(raw: Any, backend_lang: str) -> Dict[str, Any]:
    """Bring a model's service-map reply into the shape validate_service_map expects.

    Accepts a dict, a bare services list, or JSON text; drops unusable entries (logged) and
    fills missing lang / communication / port / message_bus. Entries without a name stay
    invalid so validate_service_map still rejects them.
    """
    if isinstance(raw, str):
        try:
            raw = extract_first_json(raw)
        except ValueError as e:
            logger.warning("p00c: service map reply has no JSON: %s", e)
            return {}
    if isinstance(raw, list):
        raw = {"services": raw}
    if not isinstance(raw, dict):
        logger.warning("p00c: service map reply is %s, not an object", type(raw).__name__)
        return {}
    out = dict(raw)
    items = raw.get("services")
    if not isinstance(items, list):
        items = [items] if isinstance(items, dict) else []
    services = [s for s in (_coerce_service(i, backend_lang) for i in items) if s]

    used_ports = set()
    for svc in services:
        if isinstance(svc.get("port"), str) and svc["port"].strip().isdigit():
            svc["port"] = int(svc["port"].strip())
        if isinstance(svc.get("port"), int):
            used_ports.add(svc["port"])
    next_port = _FIRST_PORT
    for svc in services:
        lang = str(svc.get("lang") or "").strip().lower()
        svc["lang"] = lang if lang in _VALID_LANGS else backend_lang
        comm = str(svc.get("communication") or "").strip().lower()
        svc["communication"] = comm if comm in _VALID_COMMS else "rest"
        if not isinstance(svc.get("port"), int):
            while next_port in used_ports:
                next_port += 1
            svc["port"] = next_port
            used_ports.add(next_port)
    out["services"] = services
    bus = out.get("message_bus")
    out["message_bus"] = bus.strip().lower() if isinstance(bus, str) else ""
    return out

FRAMEWORK_FOR_LANG: Dict[str, str] = {
    "go": "gin",
    "python": "fastapi",
    "typescript": "fastify",
    "java": "spring_boot",
}


def validate_service_map(raw: Dict[str, Any]) -> List[str]:
    """Return a list of validation error strings (empty = valid)."""
    errors: List[str] = []
    if not isinstance(raw, dict):
        return [f"service map must be an object, got {type(raw).__name__}"]
    services = raw.get("services")
    if not isinstance(services, list) or not services:
        errors.append("services must be a non-empty list")
        return errors

    seen_ports: set = set()
    for i, svc in enumerate(services):
        if not isinstance(svc, dict):
            errors.append(f"services[{i}]: must be an object, got {type(svc).__name__}")
            continue
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
