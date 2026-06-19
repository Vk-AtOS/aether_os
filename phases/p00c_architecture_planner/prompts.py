"""Prompt templates for the p00c architecture planner phase."""
from __future__ import annotations

SERVICE_MAP_PROMPT = """You are a senior software architect designing a microservices system.

Project specification:
\"\"\"
{spec_text}
\"\"\"

Domain: {domain}
Build profile: {profile_name}
Backend language: {backend_lang}
Performance tier: {performance_tier}

Design a microservices architecture. Rules:
- 3-7 services maximum (avoid over-engineering)
- Each service owns its own data — no shared databases
- Auth/identity is always its own service
- Name services by business capability, not technology
- Use REST for external-facing APIs, gRPC for internal service-to-service calls
- Choose message_bus only if async event flow is genuinely needed

Respond ONLY with valid JSON matching this exact schema:
{{
  "services": [
    {{
      "name": "auth-service",
      "description": "Handles user registration, login, JWT issuance",
      "lang": "{backend_lang}",
      "framework": "{backend_framework}",
      "port": 8001,
      "owns_entities": ["User", "Session", "Role"],
      "communication": "rest",
      "db": "postgres",
      "critical": true
    }}
  ],
  "message_bus": "",
  "api_gateway": "nginx",
  "shared_db": false,
  "notes": "One sentence about why this decomposition was chosen"
}}

Valid communication values: "rest" | "grpc" | "event"
Valid lang values: "go" | "python" | "typescript" | "java"
Valid message_bus values: "" | "kafka" | "rabbitmq" | "redis_streams"
Ports must start at 8001 and increment by 1 per service.
"""
