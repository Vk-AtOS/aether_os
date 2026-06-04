# AetherOS — Cost Model

This document provides unit economics for operating AetherOS at various scales. All figures are estimates based on observed pipeline behavior as of May 2026; actual costs will vary with LLM pricing changes, workload characteristics, and infrastructure choices.

---

## LLM Costs Per Pipeline Run

A standard 21-phase pipeline makes approximately 21 LLM calls (one primary call per phase, with additional calls in self-healing and review phases). Average token consumption per call is roughly 2,000 tokens (input + output combined for short to medium complexity prompts).

| Provider / Model | Cost per run (est.) | Notes |
|-----------------|---------------------|-------|
| OpenRouter — deepseek/deepseek-prover-v2:free | $0.00 | Free-tier model; variable availability and rate limits; suitable for development and demos |
| Anthropic — claude-sonnet-4-6 | $0.02 – $0.08 | ~21 calls × avg 2K tokens × $0.003/1K input + $0.015/1K output; scales with prompt complexity |
| Google — Gemini 2.5 Flash | $0.01 – $0.03 | Lowest cost among capable models; ~21 calls × avg 2K tokens at Gemini Flash pricing |
| Ollama (self-hosted) | $0.00 (compute only) | Eliminates per-token cost; requires GPU server; latency higher than hosted APIs |

### Notes on Token Usage

- **Simple apps** (3-5 entities, single domain): ~1,000–1,500 tokens/call → lower end of range
- **Complex apps** (10+ entities, multiple integrations, multi-domain compliance): ~3,000–5,000 tokens/call → higher end; cost may reach $0.15–0.25/run with Claude
- **Self-healing phase (p07b)**: adds 1–3 extra LLM calls per failing test; budgets should account for ~10% overhead on average
- The model router falls back through the tier hierarchy (Anthropic → Gemini → OpenRouter → Ollama) on API errors, which can affect cost if fallback models have different pricing

---

## Infrastructure Requirements

### Minimum (Development / Low Volume)

| Component | Spec | Estimated monthly cost |
|-----------|------|----------------------|
| VPS (application server) | 2 vCPU, 4 GB RAM | $20 – $40 (DigitalOcean Droplet, Hetzner CX22) |
| PostgreSQL | Included on VPS | $0 (co-located) |
| Redis | Included on VPS | $0 (co-located) |
| Storage (artifacts) | 20 GB SSD (included in most VPS plans) | $0 |
| **Total** | | **$20 – $40/month** |

Suitable for: development, demos, fewer than 20 runs/month.

Constraint: co-located Postgres and Redis compete for RAM with the application; pipeline runs are serialised in practice.

### Recommended (Production / Small Team)

| Component | Spec | Estimated monthly cost |
|-----------|------|----------------------|
| VPS (application server) | 4 vCPU, 8 GB RAM | $40 – $80 (DigitalOcean General Purpose, Hetzner CX32) |
| PostgreSQL | Managed (DigitalOcean Managed DB, Supabase free tier) | $10 – $25 |
| Redis | Managed (Redis Cloud Essentials, 100 MB) | $0 – $7 |
| Storage (artifacts) | Object storage or additional volume | $5 – $10 |
| **Total** | | **$55 – $122/month** |

Suitable for: small agencies, teams of 5–20, up to 200 runs/month.

### Scale (Multi-Tenant SaaS)

| Component | Spec | Estimated monthly cost |
|-----------|------|----------------------|
| Application servers (3×) | 4 vCPU, 8 GB RAM each | $120 – $240 |
| Load balancer | nginx / cloud LB | $10 – $20 |
| PostgreSQL | Managed, 2 vCPU, 4 GB RAM | $50 – $100 |
| Redis | Managed, 1 GB cluster | $15 – $30 |
| Object storage | 500 GB artifacts | $10 – $15 |
| CDN (dashboard static) | Cloudflare free tier | $0 |
| **Total** | | **$205 – $405/month** |

Suitable for: 500–2,000 runs/month, multiple concurrent pipeline workers.

---

## Per-Run Processing Time

| Complexity | Estimated duration | Phases driving duration |
|-----------|-------------------|------------------------|
| Simple (< 5 entities) | 3 – 4 minutes | p04 backend, p07 testing |
| Medium (5–10 entities) | 4 – 6 minutes | p04, p05 frontend, p07 |
| Complex (10+ entities, multi-domain) | 6 – 10 minutes | p04, p05, p07b self-healing |

Timing is dominated by LLM API latency. Self-hosted Ollama on a capable GPU (A10G or better) can reduce wall-clock time by 30–50% for code-generation phases.

---

## Scalability

The pipeline is horizontally scalable via the Redis MessageBus architecture:

- Each pipeline run claims an independent Redis key namespace (`aether:bus:{run_id}:*`)
- Multiple worker processes can each handle one active pipeline run concurrently
- The `PipelineService` is stateless; workers coordinate only through Redis and the shared database
- Adding a worker requires no configuration change: start an additional uvicorn process pointing at the same Redis and database

**Practical throughput**:
- 1 worker: ~6–12 runs/hour (depending on run complexity and LLM speed)
- 3 workers: ~18–36 runs/hour
- Rate limits from LLM providers (e.g., Anthropic's RPM limits) are the binding constraint at higher concurrency, not the application layer

---

## Total Cost at Representative Volumes

### 100 runs/month

| Cost component | Low estimate | High estimate |
|---------------|-------------|--------------|
| Infrastructure (recommended tier) | $55 | $122 |
| LLM — Claude Sonnet 4.6 (~21 calls × 2K tokens avg) | $2 | $8 |
| LLM — Gemini 2.5 Flash (alternative) | $1 | $3 |
| **Total (Claude)** | **$57** | **$130** |
| **Total (Gemini)** | **$56** | **$125** |
| **Total (free models only)** | **$55** | **$122** |

### 1,000 runs/month

| Cost component | Low estimate | High estimate |
|---------------|-------------|--------------|
| Infrastructure (scale tier, 3 workers) | $205 | $405 |
| LLM — Claude Sonnet 4.6 | $20 | $80 |
| LLM — Gemini 2.5 Flash (alternative) | $10 | $30 |
| **Total (Claude)** | **$225** | **$485** |
| **Total (Gemini)** | **$215** | **$435** |

**Cost per run at 1,000 runs/month**: $0.22 – $0.49 (Claude), $0.22 – $0.44 (Gemini).

---

## Revenue Model Considerations (for Acquirer Reference)

At a $49/month individual plan permitting 50 runs/month, the gross margin at 1,000 active subscribers (50,000 runs/month) is approximately:

- Revenue: $49,000/month
- Infrastructure (scaled): ~$2,000/month (economies of scale)
- LLM costs (Gemini, mixed complexity): ~$500 – $1,500/month
- **Gross margin**: ~93 – 95%

This is an illustrative model. Actual margins depend on plan mix, average run complexity, LLM pricing negotiations, and support costs.
