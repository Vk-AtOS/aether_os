"""
AetherOS stack profile registry.

A StackProfile describes the complete technology choices for a generated project.
P00 classifies the user's spec into a profile; all downstream phases read it to
decide what generators, prompts, and infrastructure to use.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class StackProfile:
    name: str
    build_type: str          # web_app | microservice | mobile | desktop | cli | ml_pipeline
    architecture: str        # monolith | microservices | serverless | event_driven
    backend_lang: str        # python | go | typescript | java
    backend_framework: str   # fastapi | gin | express | fastify | spring_boot
    frontend_framework: str  # react | react_native | flutter | electron | none
    db_primary: str          # postgres | sqlite | mysql | mongodb | timescaledb
    db_secondary: List[str] = field(default_factory=list)   # e.g. ["redis", "elasticsearch"]
    message_queue: str = ""  # "" | kafka | rabbitmq | redis_streams
    deployment_target: str = "docker_compose"  # docker_compose | kubernetes | serverless | native
    performance_tier: str = "standard"  # standard | high_throughput | real_time | batch
    description: str = ""


# Central registry — all supported build profiles.
# The LLM classifier in stack_selector.py maps a user spec to one of these keys.
STACK_PROFILES: Dict[str, StackProfile] = {
    "web_saas": StackProfile(
        name="web_saas",
        description="Standard SaaS web app — FastAPI backend, React frontend, PostgreSQL.",
        build_type="web_app",
        architecture="monolith",
        backend_lang="python",
        backend_framework="fastapi",
        frontend_framework="react",
        db_primary="postgres",
        db_secondary=["redis"],
        deployment_target="docker_compose",
        performance_tier="standard",
    ),
    "web_saas_sqlite": StackProfile(
        name="web_saas_sqlite",
        description="Lightweight SaaS web app — FastAPI backend, React frontend, SQLite.",
        build_type="web_app",
        architecture="monolith",
        backend_lang="python",
        backend_framework="fastapi",
        frontend_framework="react",
        db_primary="sqlite",
        deployment_target="docker_compose",
        performance_tier="standard",
    ),
    "go_api": StackProfile(
        name="go_api",
        description="High-performance Go/Gin REST API with React dashboard, PostgreSQL.",
        build_type="web_app",
        architecture="monolith",
        backend_lang="go",
        backend_framework="gin",
        frontend_framework="react",
        db_primary="postgres",
        db_secondary=["redis"],
        deployment_target="kubernetes",
        performance_tier="high_throughput",
    ),
    "go_microservices": StackProfile(
        name="go_microservices",
        description="Multi-service Go/Gin architecture with Kafka, Kubernetes deployment.",
        build_type="microservice",
        architecture="microservices",
        backend_lang="go",
        backend_framework="gin",
        frontend_framework="react",
        db_primary="postgres",
        db_secondary=["redis"],
        message_queue="kafka",
        deployment_target="kubernetes",
        performance_tier="high_throughput",
    ),
    "node_api": StackProfile(
        name="node_api",
        description="TypeScript/Fastify REST API with React frontend.",
        build_type="web_app",
        architecture="monolith",
        backend_lang="typescript",
        backend_framework="fastify",
        frontend_framework="react",
        db_primary="postgres",
        db_secondary=["redis"],
        deployment_target="docker_compose",
        performance_tier="standard",
    ),
    "node_serverless": StackProfile(
        name="node_serverless",
        description="TypeScript/Express serverless functions with React frontend.",
        build_type="web_app",
        architecture="serverless",
        backend_lang="typescript",
        backend_framework="express",
        frontend_framework="react",
        db_primary="postgres",
        deployment_target="serverless",
        performance_tier="standard",
    ),
    "java_enterprise": StackProfile(
        name="java_enterprise",
        description="Java Spring Boot enterprise app with React frontend, PostgreSQL.",
        build_type="web_app",
        architecture="monolith",
        backend_lang="java",
        backend_framework="spring_boot",
        frontend_framework="react",
        db_primary="postgres",
        db_secondary=["redis"],
        deployment_target="kubernetes",
        performance_tier="high_throughput",
    ),
    "mobile_react_native": StackProfile(
        name="mobile_react_native",
        description="React Native mobile app with Python/FastAPI backend.",
        build_type="mobile",
        architecture="monolith",
        backend_lang="python",
        backend_framework="fastapi",
        frontend_framework="react_native",
        db_primary="postgres",
        deployment_target="docker_compose",
        performance_tier="standard",
    ),
    "desktop_electron": StackProfile(
        name="desktop_electron",
        description="Electron desktop app with local Python/FastAPI backend and SQLite.",
        build_type="desktop",
        architecture="monolith",
        backend_lang="python",
        backend_framework="fastapi",
        frontend_framework="electron",
        db_primary="sqlite",
        deployment_target="native",
        performance_tier="standard",
    ),
    "cli_tool": StackProfile(
        name="cli_tool",
        description="Python CLI tool with no frontend, SQLite for local state.",
        build_type="cli",
        architecture="monolith",
        backend_lang="python",
        backend_framework="fastapi",  # API layer for data access
        frontend_framework="none",
        db_primary="sqlite",
        deployment_target="native",
        performance_tier="standard",
    ),
    "cli_go": StackProfile(
        name="cli_go",
        description="Go/Cobra CLI tool — ideal for high-performance devtools and automation.",
        build_type="cli",
        architecture="monolith",
        backend_lang="go",
        backend_framework="gin",
        frontend_framework="none",
        db_primary="sqlite",
        deployment_target="native",
        performance_tier="standard",
    ),
    "desktop_tauri": StackProfile(
        name="desktop_tauri",
        description="Electron desktop app with embedded FastAPI backend and SQLite.",
        build_type="desktop",
        architecture="monolith",
        backend_lang="python",
        backend_framework="fastapi",
        frontend_framework="electron",
        db_primary="sqlite",
        deployment_target="native",
        performance_tier="standard",
    ),
    "ml_pipeline": StackProfile(
        name="ml_pipeline",
        description="ML training pipeline with FastAPI serving layer, Celery workers, React dashboard.",
        build_type="ml_pipeline",
        architecture="event_driven",
        backend_lang="python",
        backend_framework="fastapi",
        frontend_framework="react",
        db_primary="postgres",
        db_secondary=["redis"],
        message_queue="redis_streams",
        deployment_target="docker_compose",
        performance_tier="batch",
    ),
    "realtime_app": StackProfile(
        name="realtime_app",
        description="Real-time collaborative app with WebSockets, Go backend, React frontend.",
        build_type="web_app",
        architecture="event_driven",
        backend_lang="go",
        backend_framework="gin",
        frontend_framework="react",
        db_primary="postgres",
        db_secondary=["redis"],
        message_queue="redis_streams",
        deployment_target="kubernetes",
        performance_tier="real_time",
    ),
    "cloud_platform": StackProfile(
        name="cloud_platform",
        description="Cloud management platform — service catalog, resource explorer, IAM, billing dashboard, multi-region.",
        build_type="cloud_platform",
        architecture="microservices",
        backend_lang="python",
        backend_framework="fastapi",
        frontend_framework="react",
        db_primary="postgres",
        db_secondary=["redis"],
        message_queue="kafka",
        deployment_target="kubernetes",
        performance_tier="high_throughput",
    ),
    "microservices": StackProfile(
        name="microservices",
        description="Go micro-services with Kafka event bus, gRPC inter-service comms, Kubernetes deployment.",
        build_type="microservice",
        architecture="microservices",
        backend_lang="go",
        backend_framework="gin",
        frontend_framework="react",
        db_primary="postgres",
        db_secondary=["redis"],
        message_queue="kafka",
        deployment_target="kubernetes",
        performance_tier="high_throughput",
    ),
    "mobile_rn": StackProfile(
        name="mobile_rn",
        description="React Native mobile app (Expo Router) backed by a FastAPI REST API.",
        build_type="mobile",
        architecture="monolith",
        backend_lang="python",
        backend_framework="fastapi",
        frontend_framework="react_native",
        db_primary="postgres",
        db_secondary=["redis"],
        deployment_target="docker_compose",
        performance_tier="standard",
    ),
}

# Default when classification fails or is ambiguous
DEFAULT_PROFILE = STACK_PROFILES["web_saas"]


def get_profile(name: str) -> StackProfile:
    """Return a profile by name, falling back to web_saas if unknown."""
    return STACK_PROFILES.get(name, DEFAULT_PROFILE)


def profile_to_dict(profile: StackProfile) -> dict:
    """Serialise a StackProfile to a plain dict for JSON output."""
    return {
        "name": profile.name,
        "build_type": profile.build_type,
        "architecture": profile.architecture,
        "backend_lang": profile.backend_lang,
        "backend_framework": profile.backend_framework,
        "frontend_framework": profile.frontend_framework,
        "db_primary": profile.db_primary,
        "db_secondary": profile.db_secondary,
        "message_queue": profile.message_queue,
        "deployment_target": profile.deployment_target,
        "performance_tier": profile.performance_tier,
        "description": profile.description,
    }
