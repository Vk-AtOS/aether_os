"""
Aether-One Prompt & Domain Template Engine

Purpose
-------
Provide structured, reusable prompt templates for different industries and tasks.

This module is pure Python, offline, and deterministic. Other components
(fix engine, plugin/framework generators, IoT agents, etc.) can call into
this to obtain:

- A "system" prompt (role / rules)
- A "user" prompt (task + requirements)
- Optional "examples" (few-shot hints)

Key concepts
------------
- Domain: e.g. "fintech", "healthcare", "iot", "gaming", "erp".
- Task: e.g. "app_scaffold", "api_design", "data_pipeline", "firmware_stub".
- Target: technology / framework target, e.g. "django", "nextjs", "ros", "firmware_c".

The output is a PromptBundle which can be fed directly to the local LLM
(including via the AI arbitration layer).
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class PromptExample:
    """
    A single example of input + ideal output, for few-shot hints.
    """

    title: str
    user_input: str
    ideal_output: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PromptBundle:
    """
    Structured prompt for a given (domain, task, target).

    - system: role + rules for the model
    - user: actual task description, with slots filled
    - examples: optional few-shot demonstrations
    - metadata: opaque dict for downstream routing or logging
    """

    domain: str
    task: str
    target: str

    system: str
    user: str
    examples: List[PromptExample] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["examples"] = [ex.to_dict() for ex in self.examples]
        return d


# ---------------------------------------------------------------------------
# Built-in template registry
# ---------------------------------------------------------------------------


# We keep a small but powerful built-in registry that can be extended later.
# Keys are (domain, task, target). Values are callables that accept requirements/context.
_TEMPLATE_REGISTRY = {}


def register_template(domain: str, task: str, target: str):
    """
    Decorator to register a template builder for a given (domain, task, target).
    """

    def _decorator(fn):
        key = (domain.lower(), task.lower(), target.lower())
        if key in _TEMPLATE_REGISTRY:
            raise ValueError(f"Duplicate template registration for {key}")
        _TEMPLATE_REGISTRY[key] = fn
        return fn

    return _decorator


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def list_templates() -> List[Dict[str, str]]:
    """
    Return a list of available (domain, task, target) combinations.

    Intended for UX (e.g. /templates/list endpoint, CLI help).
    """
    result = []
    for (domain, task, target), fn in sorted(_TEMPLATE_REGISTRY.items()):
        result.append(
            {
                "domain": domain,
                "task": task,
                "target": target,
                "builder": fn.__name__,
            }
        )
    return result


def build_prompt_bundle(
    domain: str,
    task: str,
    target: str,
    requirements: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> PromptBundle:
    """
    Build a PromptBundle for the given combination.

    Raises:
        KeyError if the (domain, task, target) is not supported.
    """
    key = (domain.lower(), task.lower(), target.lower())
    if key not in _TEMPLATE_REGISTRY:
        raise KeyError(f"No prompt template registered for {key}")

    builder = _TEMPLATE_REGISTRY[key]
    return builder(requirements or "", context or {})


# ---------------------------------------------------------------------------
# Template builders
# ---------------------------------------------------------------------------


@register_template("fintech", "app_scaffold", "django")
def _tpl_fintech_app_scaffold_django(
    requirements: str,
    context: Dict[str, Any],
) -> PromptBundle:
    """
    FinTech microservice / app scaffold using Django.

    Use this when a client wants a FinTech web backend:

    - Clean separation of concerns
    - Regulatory-grade logging
    - Strong input validation
    - Clear TODO markers for compliance checks
    """
    system = (
        "You are a senior FinTech backend engineer building a Django service. "
        "You are extremely conservative about security, correctness, and compliance. "
        "You must NEVER hardcode secrets or API keys. "
        "You MUST include docstrings and inline comments where risk or compliance applies."
    )

    user_lines = [
        "Build a Django project skeleton for a FinTech backend service.",
        "The service should expose a clean REST API for core operations.",
        "",
        "Mandatory qualities:",
        "- Strong validation on all external inputs.",
        "- Clear separation between views, serializers, and business logic.",
        "- Centralized error handling and logging.",
        "- Hooks for audit logging and risk checks.",
        "",
        f"Client requirements (free-form):\n{requirements or '[none provided]'}",
    ]

    meta = {
        "industry": "fintech",
        "risk_level": "high",
        "regulatory_notes": ["PCI-DSS", "KYC/AML (TODO hooks only, no legal advice)"],
        "framework": "django",
        "task_type": "app_scaffold",
    }

    examples = [
        PromptExample(
            title="Basic account service structure",
            user_input="Create a simple accounts app with user, account, and transaction models.",
            ideal_output=(
                "Django project layout with:\n"
                "- accounts/models.py defining UserProfile, Account, Transaction\n"
                "- accounts/views.py with class-based views for CRUD\n"
                "- urls.py wiring /api/accounts/... endpoints\n"
                "- settings snippets for DRF, logging, and security middlewares"
            ),
        )
    ]

    return PromptBundle(
        domain="fintech",
        task="app_scaffold",
        target="django",
        system=system,
        user="\n".join(user_lines),
        examples=examples,
        metadata=meta,
    )


@register_template("iot", "firmware_stub", "firmware_c")
def _tpl_iot_firmware_stub(
    requirements: str,
    context: Dict[str, Any],
) -> PromptBundle:
    """
    IoT firmware skeleton in C / C-like pseudocode.

    Use for edge devices and motor controllers.

    We do NOT guess specific chip registers; instead, we expose clear abstractions
    and TODO points for hardware-specific details.
    """
    system = (
        "You are an embedded systems engineer writing safe, portable firmware C. "
        "You must avoid undefined behavior, dynamic allocation on tiny MCUs, "
        "and any unsafe pointer tricks. Prefer clear, testable code."
    )

    device_type = context.get("device_type", "generic microcontroller")
    comms = context.get("comms", ["uart"])
    comms_str = ", ".join(comms)

    user_lines = [
        f"Generate a firmware skeleton in C for an IoT {device_type}.",
        f"Primary communication interfaces: {comms_str}",
        "",
        "The code should include:",
        "- Initialization routines for clocks, GPIO, and communication peripherals (as abstraction layers).",
        "- A main control loop with a clear state machine.",
        "- Hooks for sensor reading, actuation, and error handling.",
        "- Clear TODO markers where chip- or board-specific details must be implemented.",
        "",
        f"Functional requirements:\n{requirements or '[none provided]'}",
    ]

    meta = {
        "industry": "iot",
        "risk_level": "medium",
        "framework": "bare_metal_c",
        "task_type": "firmware_stub",
    }

    examples = [
        PromptExample(
            title="Motor controller loop",
            user_input="Device controls a single DC motor and reports RPM via UART.",
            ideal_output=(
                "C file with:\n"
                "- motor_init(), uart_init(), sensor_init()\n"
                "- main() with while(1) { read_sensor(); update_control(); send_status(); }\n"
                "- comments where hardware registers must be adapted"
            ),
        )
    ]

    return PromptBundle(
        domain="iot",
        task="firmware_stub",
        target="firmware_c",
        system=system,
        user="\n".join(user_lines),
        examples=examples,
        metadata=meta,
    )


@register_template("healthcare", "app_scaffold", "nextjs")
def _tpl_healthcare_app_scaffold_nextjs(
    requirements: str,
    context: Dict[str, Any],
) -> PromptBundle:
    """
    Healthcare front-end app scaffold in Next.js / React.

    Privacy and access control are critical. No actual PHI should be hardcoded;
    only layout, components, and placeholders.
    """
    system = (
        "You are a senior frontend engineer building healthcare-grade UIs. "
        "You must design for privacy, role-based access, and auditability. "
        "Do not include any real patient data. Use placeholders only."
    )

    user_lines = [
        "Create a Next.js app scaffold for a healthcare portal.",
        "Include:",
        "- Login/registration pages with role selection (patient, clinician, admin).",
        "- Dashboard layouts for each role.",
        "- Components for viewing and annotating records (placeholder data only).",
        "- Clear TODOs for integrating with backend APIs and authentication.",
        "",
        f"Client requirements:\n{requirements or '[none provided]'}",
    ]

    meta = {
        "industry": "healthcare",
        "risk_level": "high",
        "framework": "nextjs",
        "task_type": "app_scaffold",
    }

    return PromptBundle(
        domain="healthcare",
        task="app_scaffold",
        target="nextjs",
        system=system,
        user="\n".join(user_lines),
        examples=[],
        metadata=meta,
    )


@register_template("gaming", "app_scaffold", "unity_csharp")
def _tpl_gaming_app_scaffold_unity(
    requirements: str,
    context: Dict[str, Any],
) -> PromptBundle:
    """
    Gaming prototype scaffold in Unity / C#.

    Focus on architecture and clean separation (GameManager, UI, Systems).
    """
    system = (
        "You are a game systems engineer using Unity and C#. "
        "You must design clean, extensible game architecture, not just scripts."
    )

    genre = context.get("genre", "arcade")
    user_lines = [
        f"Create a Unity project scaffold for a {genre} game.",
        "Include:",
        "- GameManager for state transitions (menu, gameplay, pause).",
        "- Input handling layer.",
        "- Basic UI framework (menus, HUD).",
        "- Hooks for saving/loading game state.",
        "",
        f"Design requirements:\n{requirements or '[none provided]'}",
    ]

    meta = {
        "industry": "gaming",
        "risk_level": "low",
        "framework": "unity",
        "task_type": "app_scaffold",
    }

    return PromptBundle(
        domain="gaming",
        task="app_scaffold",
        target="unity_csharp",
        system=system,
        user="\n".join(user_lines),
        examples=[],
        metadata=meta,
    )


@register_template("erp", "app_scaffold", "fastapi")
def _tpl_erp_app_scaffold_fastapi(
    requirements: str,
    context: Dict[str, Any],
) -> PromptBundle:
    """
    ERP-style backend with FastAPI.

    Emphasis on modularity, multi-tenant readiness, and extensibility.
    """
    system = (
        "You are an enterprise backend architect designing modular ERP systems. "
        "You must favour clear module boundaries and explicit API contracts."
    )

    modules = context.get("modules", ["inventory", "orders", "billing"])
    modules_str = ", ".join(modules)

    user_lines = [
        "Generate a FastAPI backend scaffold for an ERP system.",
        f"Initial functional areas: {modules_str}",
        "",
        "Include:",
        "- Modular router layout (one router per module).",
        "- Pydantic models for core entities.",
        "- Basic in-memory or stubbed persistence layer (no real DB required yet).",
        "- Clear TODO comments for auth, RBAC, and multi-tenant support.",
        "",
        f"Business requirements:\n{requirements or '[none provided]'}",
    ]

    meta = {
        "industry": "erp",
        "risk_level": "medium",
        "framework": "fastapi",
        "task_type": "app_scaffold",
    }

    return PromptBundle(
        domain="erp",
        task="app_scaffold",
        target="fastapi",
        system=system,
        user="\n".join(user_lines),
        examples=[],
        metadata=meta,
    )

