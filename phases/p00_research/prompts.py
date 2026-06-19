"""Prompt templates for the P00 research and classification phases."""
from __future__ import annotations

STACK_CLASSIFIER_PROMPT = """You are a software architect classifying a build request.

User spec:
\"\"\"
{spec_text}
\"\"\"

Domain: {domain}

Based on the spec, choose the single best build profile from this list:

- web_saas          — Standard SaaS web app (FastAPI + React + PostgreSQL)
- web_saas_sqlite   — Lightweight web app (FastAPI + React + SQLite)
- go_api            — High-performance Go/Gin REST API + React dashboard
- go_microservices  — Multi-service Go architecture with Kafka + Kubernetes
- node_api          — TypeScript/Fastify REST API + React frontend
- node_serverless   — TypeScript/Express serverless + React frontend
- java_enterprise   — Java Spring Boot enterprise app + React + PostgreSQL
- mobile_react_native — React Native mobile app + Python/FastAPI backend
- desktop_electron  — Electron desktop app + local FastAPI + SQLite
- cli_tool          — Python CLI tool, no frontend
- ml_pipeline       — ML pipeline with FastAPI serving + Celery workers + React dashboard
- realtime_app      — Real-time collaborative app with WebSockets, Go + React

Decision rules:
- If spec mentions "mobile app", "iOS", "Android", "phone" → mobile_react_native
- If spec mentions "desktop", "offline", "local install" → desktop_electron
- If spec mentions "CLI", "command line", "terminal tool" → cli_tool
- If spec mentions "high throughput", "millions of requests", "Go", "Rust" → go_api
- If spec mentions "microservices", "service mesh", "multiple services" → go_microservices
- If spec mentions "machine learning", "training", "model serving", "ML" → ml_pipeline
- If spec mentions "real-time", "collaborative", "live updates", "WebSocket" → realtime_app
- If spec mentions "Java", "Spring", "enterprise" → java_enterprise
- If spec mentions "serverless", "Lambda", "edge functions" → node_serverless
- If spec mentions "TypeScript", "Node", "Fastify", "Express" → node_api
- Otherwise → web_saas (for postgres-heavy) or web_saas_sqlite (for simpler apps)

Respond with ONLY valid JSON, no explanation:
{{
  "profile": "<profile_name>",
  "confidence": <0.0-1.0>,
  "reason": "<one sentence>"
}}
"""

DESIGN_BRIEF_LLM_FALLBACK_PROMPT = """
Envision the design patterns for a top-tier {domain} web application.
Think about sites like {competitor_sites}.
Extract:
1. Navigation style (e.g. sticky top nav, sidebar)
2. Primary color family (e.g. indigo-600, slate-900)
3. Essential customer features
4. Key UI components (e.g. hero search, data tables, Kanban)
Return JSON.
"""
