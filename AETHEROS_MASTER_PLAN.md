# AetherOS — Master Plan & Complete Fix Registry
**Date Compiled:** 2026-05-10  
**Scope:** Every fix, architectural decision, broken wiring, incomplete workflow, security vulnerability, and product requirement for AetherOS — the autonomous AI software factory.  
**Target:** Production-grade, 5 million concurrent users, hyper-defensible, unbreakable generated code, per-user isolated learning loop.

---

# TABLE OF CONTENTS

1. [Project Overview & What AetherOS Is](#1-project-overview)
2. [Architecture Decisions & Current Module Map](#2-architecture-decisions)
3. [Product Requirements — What Must Be Built](#3-product-requirements)
4. [Per-User Isolated Learning Loop (Core Moat)](#4-learning-loop)
5. [5 Million User Scale Design](#5-scale-design)
6. [Frontend Builder Tab — Complete Spec](#6-frontend-builder)
7. [Backend Builder — Complete Spec](#7-backend-builder)
8. [Prompt Input Tab — Complete Spec](#8-prompt-input-tab)
9. [Hyper-Defensible Generated Code Standard](#9-generated-code-security)
10. [Module Wiring Cross-Check](#10-module-wiring)
11. [CRITICAL Fixes — Pipeline-Breaking (Fix First)](#11-critical-fixes)
12. [Security Vulnerabilities — Full Registry](#12-security-vulnerabilities)
13. [API Stubs & Incomplete Endpoints](#13-api-stubs)
14. [Frontend Bugs & Missing UI](#14-frontend-bugs)
15. [Legal, Regulatory & Compliance Gaps](#15-compliance)
16. [Attack Vector Registry (52 vectors)](#16-attack-vectors)
17. [Infrastructure Failure Modes (47 scenarios)](#17-failure-modes)
18. [Incomplete & Interrupted Workflows](#18-incomplete-workflows)
19. [Cost Reduction Strategy](#19-cost-reduction)
20. [Hardening Checklist (100/100 benchmark)](#20-hardening-checklist)
21. [Fix Priority Order — Sequenced Execution Plan](#21-fix-sequence)

---

# 1. PROJECT OVERVIEW

AetherOS is an autonomous AI software factory. Users submit a natural language requirement. AetherOS runs a 12-phase pipeline that produces a fully deployed, tested, production-grade application — backend, frontend, CI/CD, docs, monitoring, and live URL — with zero human coding required.

## What Exists Today (Modules Built)

| Module | Path | Status |
|--------|------|--------|
| FastAPI Gateway | `gateway/api.py` | 2,350 lines, 65 routes, partially broken |
| JWT Auth | `gateway/auth.py` | Working but missing jti/revocation |
| SAML SSO | `gateway/auth_saml.py` | Flask stub — never mounts in FastAPI |
| Pipeline Orchestrator | `orchestrator/pipeline.py` | 645 lines, 2 broken imports |
| Factory Pipeline | `orchestrator/factory_pipeline.py` | 512 lines, SQLite writes, in-process dicts |
| Phase P01–P11 | `phases/` | 12 consolidated + 34 legacy in `_legacy/` |
| LLM Client | `core/llm/client.py` | Working, no connection reuse |
| Model Router | `core/model_router.py` | Orphaned — not imported anywhere |
| Memory Manager | `core/memory/memory_manager.py` | Orphaned — broken import in pipeline |
| Memory Store | `core/memory/store.py` | SQLite, not PostgreSQL |
| Memory Matcher | `core/memory/matcher.py` | Broken import — always fails |
| Decision Engine | `core/decision_engine.py` | Partially wired |
| Audit Ledger | `core/audit/ledger.py` | SQLite (should be PostgreSQL ORM) |
| Billing | `core/billing.py` | SQLite (should be PostgreSQL ORM) |
| Approval Store | `core/approval/store.py` | SQLite (should be PostgreSQL ORM) |
| Artifact Store | `core/artifact_store.py` | SQLite O(N) scan (should be PostgreSQL pgvector) |
| Rate Limiter | `core/rate_limiter.py` | Sync Redis (should be async) |
| ORM Models | `core/models.py` | All models defined, some never used |
| Database | `core/db.py` | Pool overflow + DDL bug |
| Sandbox Guard | `core/sandbox/guard.py` | Regex-based, bypassable |
| Plugin System | `core/plugins/skills.py` | 10 skills all `pass` body |
| Connectors | `core/plugins/connectors.py` | Base class only, `pass` body |
| Policy Engine | `core/policy/compliance.py` | Implemented but never wired to UI |
| Zero-Trust | `core/zero_trust/` | Implemented, partially wired |
| LLM Cache | `core/llm/cache.py` | Working, missing org_id in cache key |
| Token Budget | `core/llm/budget.py` | Working |
| React Dashboard | `dashboard/src/` | 15+ pages, multiple broken |
| Nginx Config | `deploy/nginx.conf` | Configured |
| Systemd Service | `deploy/aetheros.service` | `ProtectHome=yes` breaks data dir |
| VPS Setup | `deploy/setup_vps.sh` | Ollama exposed on 0.0.0.0 |

---

# 2. ARCHITECTURE DECISIONS

## 2.1 The Core Problem: Why Redesign Was Needed

The original AetherOS grew organically. Key structural problems:

1. **Split-brain database**: 6 different SQLite files + PostgreSQL ORM. Data lives in 7 places. No foreign keys across stores. Dashboard reads from SQLite ledger; auth reads from PostgreSQL — relationships are physically impossible.
2. **In-process state in multi-worker deployment**: `PIPELINE_EVENTS` and `PIPELINE_CONTROL` are Python dicts in one process. With 8 uvicorn workers, a pipeline started in Worker 1 is invisible to all other workers. SSE streaming and pause/cancel fail 7/8 of the time.
3. **22 of 25 pipeline sub-phase imports fail silently**: All consolidated phases import from `aether_os.phases.pXX_*` but the modules live at `phases/_legacy/pXX_*/`. Every import fails with `ModuleNotFoundError` caught by `try/except: pass`. The pipeline runs "successfully" producing empty output.
4. **Monolith**: 2,350-line `api.py`. Untestable, unmaintainable.
5. **No learning**: Memory system exists but: wrong import path = broken, SQLite = per-worker, no cross-run pattern extraction.

## 2.2 Target Architecture (Post-Fix)

```
┌─────────────────────────────────────────────────────────┐
│                    User (Browser)                        │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐    │
│  │ Prompt Input │ │Frontend Build│ │Backend Build  │    │
│  │     Tab      │ │     Tab      │ │     Tab       │    │
│  └──────┬───────┘ └──────┬───────┘ └──────┬────────┘   │
└─────────┼────────────────┼────────────────┼─────────────┘
          │ HTTPS / WSS    │                │
┌─────────▼────────────────▼────────────────▼─────────────┐
│                Nginx (TLS termination)                    │
│           Rate limiting + DDoS protection                 │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│          FastAPI Gateway (8 workers via uvicorn)          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │auth.py   │ │factory.py│ │pipeline.py│ │admin.py  │   │
│  │saml.py   │ │webhooks  │ │events.py  │ │compliance│   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
└───────┬──────────────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────┐
│                    Service Layer                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │Learning  │ │Decision  │ │Memory    │ │Billing   │   │
│  │Service   │ │Engine    │ │Service   │ │Service   │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
└───────┬──────────────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────┐
│              Shared State (Cross-Worker)                  │
│  ┌──────────────────────┐  ┌──────────────────────────┐  │
│  │     Redis             │  │   PostgreSQL (PgBouncer) │  │
│  │  - SSE events pub/sub│  │  - All ORM data          │  │
│  │  - Pipeline control   │  │  - Per-user learning     │  │
│  │  - Rate limiting      │  │  - Audit logs            │  │
│  │  - SSE token exchange │  │  - Memory patterns       │  │
│  │  - JWT blacklist      │  │  - Artifact embeddings   │  │
│  └──────────────────────┘  └──────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────┐
│              Pipeline Orchestrator                        │
│  P01→P02→P03→P04→P05→P06→P07→P07b→P08→P09→P10→P11     │
│  Requirements→Architecture→Scaffold→Backend→Frontend→    │
│  Review→Test→Self-Heal→CICD→Observability→Docs→Deploy   │
└───────┬──────────────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────┐
│              Docker Sandbox (Generated Apps)              │
│  --network=aetheros-isolated --user=1001 --read-only     │
│  Seccomp profile + resource limits + health checks       │
└──────────────────────────────────────────────────────────┘
```

## 2.3 Database Design Decision

**Decision**: All state moves to PostgreSQL via SQLAlchemy async ORM. Redis handles ephemeral/pub-sub state. No SQLite in production.

| Data | Current | Target |
|------|---------|--------|
| Run history | SQLite ledger.py | PostgreSQL `runs` table |
| Events | SQLite ledger.py | PostgreSQL `events` table |
| Per-user learning patterns | SQLite memory/store.py | PostgreSQL `user_learning_patterns` table (org_id + user_id scoped) |
| Billing/tokens | SQLite billing.db | PostgreSQL `token_budget_records` table |
| Approval tickets | SQLite approval/store.py | PostgreSQL `decisions` table |
| Artifact embeddings | SQLite artifact_store.py | PostgreSQL `artifact_embeddings` + pgvector |
| MCP configs | SQLite mcp_router.py | PostgreSQL `installed_plugin_records` table |
| LLM cache | SQLite → PostgreSQL ✓ | PostgreSQL `llm_cache_entries` (already migrated) |
| SSE events | In-process asyncio.Queue | Redis pub/sub channel per run_id |
| Pipeline control | In-process dict | Redis key per run_id |
| Rate limits | Sync Redis | Async Redis (redis.asyncio) |
| JWT blacklist | None | Redis `revoked_token:{jti}` with TTL |
| SSE tokens | Already Redis ✓ | Redis (done) |

---

# 3. PRODUCT REQUIREMENTS

## 3.1 Core Product: What AetherOS Must Do

1. **Accept natural language requirements** via a Prompt Input Tab
2. **Run a 12-phase pipeline** producing a complete, deployed application
3. **Show live progress** via SSE streaming terminal in the UI
4. **Enable human-in-the-loop** approvals at configurable pipeline gates
5. **Deliver artifacts**: source code, tests, docs, live URL
6. **Learn per-user**: every run improves future runs for that user only (see Section 4)
7. **Support enterprise**: SAML SSO, SCIM 2.0, RBAC, audit logs, compliance reports
8. **Generate hyper-defensible code**: every line of output passes security standards (see Section 9)
9. **Scale to 5 million concurrent users** (see Section 5)

## 3.2 New Requirements Added This Session

- **Frontend Builder Tab**: Visual drag-and-drop frontend construction integrated with pipeline output
- **Backend Builder Tab**: Schema/API design interface feeding into P04 backend phase
- **Prompt Input Tab**: Primary entry point with conversation-style interface, project-scoped only
- **Per-user isolated learning loop**: Complete design in Section 4
- **Hyper-defensible generated code**: Standard defined in Section 9

---

# 4. PER-USER ISOLATED LEARNING LOOP (CORE MOAT)

## 4.1 Design Principle

Every user's coding patterns, preferences, and domain knowledge are stored exclusively in their own learning space. Ramesh's FastAPI patterns never appear in Sadhana's completions. The system gets smarter with each run for each user, independently.

## 4.2 Data Model

```sql
-- Per-user learning patterns (never cross org/user boundaries)
CREATE TABLE user_learning_patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Pattern classification
    pattern_type VARCHAR(64) NOT NULL,  
    -- Values: 'naming_convention', 'architecture_preference', 'tech_stack', 
    --         'error_pattern', 'code_style', 'domain_expertise', 'deployment_preference'
    
    -- The learned pattern (versioned)
    pattern_key VARCHAR(256) NOT NULL,
    pattern_value JSONB NOT NULL,
    confidence FLOAT DEFAULT 0.5,       -- 0.0 to 1.0, increases with repetition
    occurrence_count INT DEFAULT 1,
    
    -- Source traceability
    source_run_ids UUID[] DEFAULT '{}', -- which runs contributed to this pattern
    last_updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Isolation guarantee: queries MUST filter by both org_id AND user_id
    UNIQUE (org_id, user_id, pattern_type, pattern_key),
    INDEX ix_learning_user (org_id, user_id, pattern_type)
);

-- Questions the system wants to ask users to improve their learning profile
CREATE TABLE learning_clarifications_pending (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    user_id UUID NOT NULL,
    run_id UUID REFERENCES runs(id),
    
    question TEXT NOT NULL,
    question_type VARCHAR(32) NOT NULL,  -- 'preference', 'clarification', 'confirmation'
    context JSONB,                        -- what prompted this question
    answered_at TIMESTAMPTZ,
    answer JSONB,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '7 days',
    
    -- Questions are scoped to project context only
    -- Valid: "Do you prefer snake_case or camelCase for your Python functions?"  
    -- Invalid: "Tell me about your personal life"
    
    CONSTRAINT question_scope_check CHECK (
        question_type IN ('preference', 'clarification', 'confirmation', 'error_fix', 'design_review')
    )
);
```

## 4.3 Learning Service Implementation

```python
# core/services/learning_service.py

class LearningService:
    """
    Per-user isolated learning loop.
    CRITICAL: All methods REQUIRE org_id + user_id. 
    Never query without both — isolation is the invariant.
    """
    
    async def extract_patterns_from_run(
        self, 
        run_id: str, 
        org_id: str, 
        user_id: str,
        session: AsyncSession
    ) -> List[LearnedPattern]:
        """
        Called after every successful pipeline phase completion.
        Analyzes output to extract user-specific patterns.
        """
        run = await session.get(Run, run_id)
        patterns = []
        
        # 1. Tech stack preferences
        if run.tech_stack:
            await self._upsert_pattern(
                org_id, user_id, "tech_stack", "preferred_stack",
                run.tech_stack, session
            )
        
        # 2. Naming conventions (from generated code)
        code_output = await self._load_phase_output(run_id, "p04_backend")
        if code_output:
            naming = await self._analyze_naming_conventions(code_output)
            await self._upsert_pattern(
                org_id, user_id, "naming_convention", "python_functions",
                naming, session
            )
        
        # 3. Architecture patterns (from P02 output)
        arch = await self._load_phase_output(run_id, "p02_architecture")
        if arch:
            await self._upsert_pattern(
                org_id, user_id, "architecture_preference", "last_architecture",
                arch, session
            )
        
        # 4. Error patterns (from P07 self-healing)
        errors = await self._load_phase_output(run_id, "p07b_self_healing")
        if errors:
            await self._upsert_error_patterns(org_id, user_id, errors, session)
        
        return patterns
    
    async def get_user_context_for_pipeline(
        self,
        org_id: str,
        user_id: str,
        session: AsyncSession
    ) -> UserLearningContext:
        """
        Retrieve all learned patterns for a specific user.
        This context is injected into every LLM prompt for that user.
        NEVER called without org_id + user_id filter.
        """
        stmt = select(UserLearningPattern).where(
            UserLearningPattern.org_id == org_id,
            UserLearningPattern.user_id == user_id,
            UserLearningPattern.confidence >= 0.3  # only confident patterns
        ).order_by(UserLearningPattern.confidence.desc()).limit(50)
        
        result = await session.execute(stmt)
        patterns = result.scalars().all()
        
        return UserLearningContext(
            naming_conventions=self._extract_by_type(patterns, "naming_convention"),
            tech_preferences=self._extract_by_type(patterns, "tech_stack"),
            architecture_patterns=self._extract_by_type(patterns, "architecture_preference"),
            domain_expertise=self._extract_by_type(patterns, "domain_expertise"),
            error_avoidance=self._extract_by_type(patterns, "error_pattern"),
        )
    
    async def generate_clarification_question(
        self,
        org_id: str,
        user_id: str,
        run_id: str,
        context: str,
        session: AsyncSession
    ) -> Optional[str]:
        """
        Generate a project-scoped clarification question.
        Questions MUST be about the project — not personal, not general.
        Returns None if no question is needed.
        
        Valid questions: 
          - "Should the authentication use JWT or sessions for this API?"
          - "Do you want the database to use soft deletes or hard deletes?"
          
        Invalid questions (blocked by prompt):
          - Anything about personal preferences unrelated to the project
          - Anything outside planning, design, execution, review, reports
        """
        # Check if we already have too many unanswered questions
        pending = await session.execute(
            select(func.count(LearningClarificationPending.id)).where(
                LearningClarificationPending.org_id == org_id,
                LearningClarificationPending.user_id == user_id,
                LearningClarificationPending.answered_at.is_(None),
                LearningClarificationPending.expires_at > func.now()
            )
        )
        if pending.scalar() >= 3:
            return None  # Don't overwhelm the user
        
        prompt = f"""You are AetherOS's learning engine. 
Based on the following project context, generate ONE specific question to improve 
code quality for this project ONLY.

RULES:
- Question must be about: requirements, architecture, code style, testing strategy, 
  deployment preferences, error handling, or design decisions FOR THIS PROJECT
- Question must NOT be about: personal preferences unrelated to code, 
  anything outside software development, personal life, opinions
- Question must be answerable in 1-3 sentences
- If no question would meaningfully improve the output, respond with: NO_QUESTION

Project context: {context[:2000]}
"""
        question = await llm_client.call_json(prompt, task_type="learning_question")
        
        if question == "NO_QUESTION" or not question:
            return None
        
        # Store the pending question
        clarification = LearningClarificationPending(
            org_id=org_id, user_id=user_id, run_id=run_id,
            question=question, question_type="clarification",
            context={"context": context[:500]}
        )
        session.add(clarification)
        await session.commit()
        
        return question
    
    async def _upsert_pattern(
        self, org_id: str, user_id: str, 
        pattern_type: str, pattern_key: str, 
        value: Any, session: AsyncSession
    ):
        """
        Upsert a learned pattern for a specific user.
        Increases confidence with each occurrence.
        """
        existing = await session.execute(
            select(UserLearningPattern).where(
                UserLearningPattern.org_id == org_id,
                UserLearningPattern.user_id == user_id,
                UserLearningPattern.pattern_type == pattern_type,
                UserLearningPattern.pattern_key == pattern_key,
            )
        )
        pattern = existing.scalar_one_or_none()
        
        if pattern:
            pattern.occurrence_count += 1
            pattern.confidence = min(1.0, pattern.confidence + 0.1)
            pattern.pattern_value = value
            pattern.last_updated_at = func.now()
        else:
            session.add(UserLearningPattern(
                org_id=org_id, user_id=user_id,
                pattern_type=pattern_type, pattern_key=pattern_key,
                pattern_value=value, confidence=0.5
            ))
        await session.commit()
```

## 4.4 Integration Points

- **Pipeline Start**: `LearningService.get_user_context_for_pipeline()` injects user-specific context into every LLM prompt system message
- **Phase Completion**: `LearningService.extract_patterns_from_run()` runs after each phase completes
- **Clarification Questions**: Surfaced in the UI as a notification after pipeline completes (max 3 pending at once)
- **Isolation Guarantee**: Every DB query that touches `user_learning_patterns` MUST include `WHERE org_id = ? AND user_id = ?`. Code review enforces this.

## 4.5 Conversation Scope Enforcement

The Prompt Input Tab (Section 8) enforces conversation scope at the prompt level:

```python
SYSTEM_PROMPT_SCOPE_GUARD = """
You are AetherOS, an autonomous software development assistant.

SCOPE RESTRICTION — ABSOLUTE:
You may ONLY discuss topics in these categories:
1. Software requirements and specifications for the current project
2. Architecture, design patterns, and technical decisions
3. Code review, debugging, and error analysis
4. Testing strategy and coverage
5. Deployment, infrastructure, and monitoring
6. Performance optimization
7. Security review of generated code
8. Documentation and API specifications
9. Change requests and iterations on the current project
10. Project planning and timeline estimation

You will REFUSE all other topics with: 
"I'm focused on your project. Let's talk about [specific project topic]. 
What aspect of the project can I help you with?"

Current project: {project_name}
User's learned preferences: {user_context}
"""
```

---

# 5. 5 MILLION USER SCALE DESIGN

## 5.1 Capacity Model

| Layer | Current | Target (5M users) |
|-------|---------|-------------------|
| Web workers | 8 (single VPS) | 200+ pods (Kubernetes) |
| PostgreSQL | 1 server, max_connections=100 | PgBouncer + read replicas |
| Redis | 1 instance | Redis Cluster (3 primary + 3 replica) |
| LLM calls | 1 provider fallback | Multi-provider load balancing |
| Pipeline workers | Same process as API | Separate Celery/ARQ worker pool |
| Storage | Local ~/.aether_os | S3-compatible object storage |
| CDN | None | CloudFront / Cloudflare |

## 5.2 Database Layer for Scale

```python
# core/db.py — production settings for 5M users

# With PgBouncer (transaction mode):
# - PgBouncer pool_size=100 per server
# - PostgreSQL max_connections=500
# - Application pool_size=2, max_overflow=5 per worker
# (PgBouncer multiplexes: 200 app connections → 100 PgBouncer → 500 PG connections)

engine = create_async_engine(
    DATABASE_URL,
    pool_size=2,              # Per worker (PgBouncer multiplexes)
    max_overflow=5,           # Burst capacity per worker
    pool_timeout=10,          # Fail fast under load
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={
        "server_settings": {
            "jit": "off",     # Faster startup for short transactions
            "application_name": "aetheros_api"
        }
    }
)
```

## 5.3 Pipeline Worker Separation

For 5M users, pipeline execution must move OUT of the API process:

```yaml
# docker-compose.prod.yml
services:
  api:
    image: aetheros-api
    command: uvicorn aether_os.gateway.api:app --workers 4
    environment:
      - WORKER_TYPE=api
    
  pipeline-worker:
    image: aetheros-pipeline
    command: arq aether_os.worker.WorkerSettings
    replicas: 20
    environment:
      - WORKER_TYPE=pipeline
    
  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    
  pgbouncer:
    image: pgbouncer/pgbouncer
    environment:
      - POOL_MODE=transaction
      - MAX_CLIENT_CONN=2000
      - DEFAULT_POOL_SIZE=100
```

## 5.4 Caching Strategy for Scale

```
User Request → CDN (static assets, 1yr TTL)
             → Nginx (rate limiting, TLS)
             → FastAPI (auth, routing)
             → Redis (LLM cache, 24h TTL) → Hit: return in 1ms
             → PostgreSQL (persistent data)
             → Anthropic API (LLM, $$$)
```

LLM cache hit rate target: 60%+ (reduces API costs by 60%)

## 5.5 Auto-Scaling Rules

```yaml
# kubernetes/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
spec:
  minReplicas: 10
  maxReplicas: 200
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        averageUtilization: 70
  - type: External  
    external:
      metric:
        name: pipeline_queue_depth
      target:
        value: "100"  # Scale up when >100 jobs queued
```

---

# 6. FRONTEND BUILDER TAB

## 6.1 Purpose

The Frontend Builder tab gives users a visual interface to specify frontend requirements before the pipeline runs P03 (scaffolding) and the frontend generation phase. It reduces LLM guesswork and produces better UI output.

## 6.2 Required Components

```
dashboard/src/pages/FrontendBuilder.jsx
dashboard/src/components/frontend-builder/
  ├── LayoutSelector.jsx        — Sidebar, topbar, dashboard, landing page
  ├── ComponentPalette.jsx      — Drag-and-drop component library
  ├── ColorThemeSelector.jsx    — Color scheme picker
  ├── PageStructure.jsx         — Page hierarchy builder (tree view)
  ├── ResponsivePreview.jsx     — Mobile/tablet/desktop preview
  └── FrontendSpecOutput.jsx    — Shows generated spec JSON
```

## 6.3 Spec Output Format (feeds into Pipeline P03)

```json
{
  "frontend_spec": {
    "framework": "react",
    "styling": "tailwindcss",
    "layout": "sidebar-dashboard",
    "color_theme": {
      "primary": "#6366f1",
      "background": "#0a0a0f",
      "surface": "#14141f"
    },
    "pages": [
      { "name": "Dashboard", "route": "/", "components": ["StatsCard", "Chart", "Table"] },
      { "name": "Settings", "route": "/settings", "components": ["Form", "Toggle"] }
    ],
    "authentication": true,
    "responsive": true,
    "dark_mode": true,
    "component_library": "shadcn-ui"
  }
}
```

## 6.4 Backend API Required

```python
# New endpoint needed:
POST /factory/runs/{run_id}/frontend-spec
GET  /factory/runs/{run_id}/frontend-spec
```

---

# 7. BACKEND BUILDER TAB

## 7.1 Purpose

The Backend Builder tab lets users define their data model and API design visually before P04 (backend codegen). Eliminates LLM hallucination of wrong schemas.

## 7.2 Required Components

```
dashboard/src/pages/BackendBuilder.jsx
dashboard/src/components/backend-builder/
  ├── EntityRelationshipDiagram.jsx  — Visual DB schema builder
  ├── APIEndpointDesigner.jsx        — REST/GraphQL endpoint designer
  ├── AuthFlowSelector.jsx           — JWT / OAuth / API Key / SAML
  ├── DatabasePicker.jsx             — PostgreSQL / MySQL / MongoDB / SQLite
  ├── BackendSpecOutput.jsx          — Shows generated spec JSON
  └── ValidationRulesBuilder.jsx     — Per-field validation rules
```

## 7.3 Spec Output Format (feeds into Pipeline P04)

```json
{
  "backend_spec": {
    "framework": "fastapi",
    "database": "postgresql",
    "orm": "sqlalchemy",
    "authentication": "jwt",
    "entities": [
      {
        "name": "User",
        "fields": [
          { "name": "id", "type": "uuid", "primary_key": true },
          { "name": "email", "type": "string", "unique": true, "max_length": 255 },
          { "name": "created_at", "type": "datetime", "auto": true }
        ]
      }
    ],
    "endpoints": [
      { "method": "GET", "path": "/users", "auth": true, "pagination": true },
      { "method": "POST", "path": "/users", "auth": true, "validate": true }
    ],
    "cors_origins": ["https://yourdomain.com"],
    "rate_limiting": true,
    "async": true
  }
}
```

## 7.4 Backend API Required

```python
POST /factory/runs/{run_id}/backend-spec
GET  /factory/runs/{run_id}/backend-spec
POST /factory/runs/{run_id}/validate-spec   — Validate before pipeline starts
```

---

# 8. PROMPT INPUT TAB

## 8.1 Purpose

The primary entry point for AetherOS. A conversation-style interface where users describe what they want to build. Every conversation is scoped to the project — no off-topic interactions.

## 8.2 UI Specification

```
dashboard/src/pages/PromptInput.jsx
dashboard/src/components/prompt/
  ├── ConversationThread.jsx     — Chat-style message history
  ├── ProjectScopeIndicator.jsx  — Shows current project context
  ├── RequirementBuilder.jsx     — Structured requirement assembly from conversation
  ├── AttachmentUpload.jsx       — Upload reference docs, wireframes, existing code
  ├── ClarificationResponder.jsx — Display pending learning questions
  └── PipelineStartButton.jsx    — "Build This" CTA when spec is ready
```

## 8.3 Conversation Flow

```
1. User types: "I want to build a SaaS project management tool"
   → System: "Got it. Who is your target user? (developers, project managers, executives)"

2. User: "Project managers in mid-size tech companies"
   → System: "What are the 3 main things they need to do? 
              (e.g., create projects, assign tasks, track progress)"

3. After 3-5 exchanges, the system assembles a structured spec
   → Shows: RequirementBuilder summary
   → CTA: "Start Building" button

4. User clicks "Start Building"
   → Pipeline starts
   → Redirects to ProjectView with live SSE terminal
```

## 8.4 Scope Enforcement

All messages go through the SYSTEM_PROMPT_SCOPE_GUARD (Section 4.5). Off-topic messages receive a redirect: "Let's focus on your project. What aspect of [project_name] should I help with?"

## 8.5 Integration with Learning Loop

- Past user preferences are injected as context into every conversation turn
- After conversation completes, patterns are extracted (preferred communication style, level of detail, tech preferences)
- Pending clarification questions (from learning service) are surfaced here, not in a separate modal

---

# 9. HYPER-DEFENSIBLE GENERATED CODE STANDARD

Every line of code AetherOS produces must meet this standard before delivery. The pipeline enforces it via P06 (security review) which is a mandatory gate — cannot be skipped.

## 9.1 Authentication & Authorization (Generated Apps)

```python
# Every generated FastAPI app gets this template:

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import bcrypt
from datetime import datetime, timedelta

# ✓ JWT with RS256 (not HS256) for generated apps
# ✓ Access tokens: 15 minutes
# ✓ Refresh tokens: 7 days, stored in httpOnly cookie
# ✓ bcrypt for passwords (not SHA-256)
# ✓ Rate limiting on auth endpoints
# ✓ Account lockout: 5 failed attempts → 15min lock
# ✓ No secrets in code — all from environment variables
```

## 9.2 Input Validation Standard

```python
# ✓ Pydantic models for ALL request bodies (no Dict[str, Any])
# ✓ Field validators with max_length, regex, ge/le bounds
# ✓ No eval(), exec(), subprocess with shell=True
# ✓ Parameterized queries only (no string interpolation in SQL)
# ✓ Path validation: never allow ../ traversal
# ✓ File upload: validate mime type AND magic bytes
```

## 9.3 Security Headers (All Generated Apps)

```python
# Every generated app gets these headers via middleware:
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; object-src 'none'",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()"
}
```

## 9.4 Generated Code Security Gate (P06 Phase — Mandatory)

The security phase runs these checks — ALL must pass before deployment:

1. **Bandit** static analysis — no HIGH or CRITICAL findings
2. **Semgrep** rules — OWASP Top 10 checks
3. **Secret detection** — no hardcoded credentials (detect-secrets)
4. **Dependency scan** — pip-audit with no CRITICAL CVEs
5. **LLM security review** — Claude reviews generated code for logic flaws
6. **CORS check** — no `allow_origins=["*"]` with `allow_credentials=True`
7. **Sandbox escape check** — no eval/exec/subprocess in generated code (real Docker test)

If any check fails: pipeline pauses and surfaces findings to user for review before proceeding.

## 9.5 Generated Dockerfile Standard

```dockerfile
FROM python:3.11-slim

# Security: create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -u 1001 appuser

# Install dependencies as root, then switch
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app and set ownership
COPY --chown=appuser:appuser . .

# Drop privileges
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run with explicit host binding to container-only interface
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--access-log", "--no-server-header"]
```

## 9.6 Docker Run Standard (p11_deployment)

```python
# Every generated container gets these flags:
docker_run_args = [
    "docker", "run", "-d",
    "--name", safe_container_name(run_id),
    "-p", f"127.0.0.1:{port}:8000",   # Bind to localhost ONLY
    "--network", "aetheros-isolated",   # No host routing
    "--memory", "512m",                 # Memory limit
    "--cpus", "0.5",                    # CPU limit
    "--read-only",                      # Read-only filesystem
    "--tmpfs", "/tmp:size=64m",         # Allow /tmp writes only
    "--restart", "on-failure:3",        # Max 3 restarts
    "--security-opt", "no-new-privileges:true",
    "--security-opt", f"seccomp={SECCOMP_PROFILE_PATH}",
    "--cap-drop", "ALL",               # Drop all Linux capabilities
    image_name
]
```

---

# 10. MODULE WIRING CROSS-CHECK

## 10.1 Import Chain Status

| Module | Imports From | Status | Fix Required |
|--------|-------------|--------|--------------|
| `gateway/api.py` | `gateway/auth.py` | ✓ OK | — |
| `gateway/api.py` | `core/rate_limiter.py` | ⚠ Sync Redis | Make async |
| `gateway/api.py` | `core/audit/ledger.py` | ✗ SQLite | Migrate to ORM |
| `gateway/api.py` | `orchestrator/pipeline.py` | ⚠ Broken run_id | Fix mismatch |
| `gateway/api.py` | `orchestrator/factory_pipeline.py` | ⚠ SQLite writes | Migrate |
| `orchestrator/pipeline.py` | `phases/pXX_*/task_agent.py` | ✓ OK | — |
| `orchestrator/pipeline.py` | `core/memory/memory_manager.py` | ✗ Wrong prefix | Fix import |
| `orchestrator/factory_pipeline.py` | `phases/_legacy/` | ✗ Not importable | Add __init__.py |
| `phases/p04_backend/task_agent.py` | `phases/_legacy/p04a_backend_codegen/` | ✗ ModuleNotFoundError | Fix |
| `phases/p06_review_security/task_agent.py` | `phases/_legacy/p05_code_review/` | ✗ ModuleNotFoundError | Fix |
| `phases/p07_testing/task_agent.py` | `phases/_legacy/p07a_*`, `p07b_*`, `p07c_*`, `p07d_*` | ✗ All fail | Fix |
| `phases/p08_cicd_deployment/task_agent.py` | `phases/_legacy/p08_cicd/`, `p10_deployment/`, `p11a-d_*` | ✗ All fail | Fix |
| `phases/p09_observability/task_agent.py` | `phases/_legacy/p11a_monitoring/`, `p12a/b/`, `p13_*` | ✗ All fail | Fix |
| `phases/p10_docs_delivery/task_agent.py` | `phases/_legacy/p09_documentation/`, `p14_*`, `p15_*` | ✗ All fail | Fix |
| `core/memory/matcher.py` | `aether_os.phases.p08_cicd.patch_reuse.fingerprint` | ✗ Legacy path | Fix |
| `core/policy/compliance.py` | (standalone) | ✓ Implemented | Wire to UI |
| `core/zero_trust/` | `gateway/api.py` | ⚠ Partial | Complete wiring |
| `gateway/auth_saml.py` | Flask app (not FastAPI) | ✗ Dead code | Rewrite as FastAPI router |
| `core/plugins/skills.py` | (standalone) | ✗ All `pass` | Implement |
| `core/plugins/connectors.py` | (standalone) | ✗ `pass` | Implement |

## 10.2 Pipeline Phase Execution Chain

```
P01 intake_requirements    ✓ Runs
P02 architecture           ✓ Runs  
P03 scaffolding            ✓ Runs (CORS wildcard bug — fix)
P04 backend_codegen        ✗ Sub-phase imports fail → empty output
P05 frontend_buildout      ✓ Runs
P06 review_security        ✗ Sub-phase imports fail → security skipped silently
P07 testing                ✗ Sub-phase imports fail + hardcoded passed:True
P07b self_healing          ✓ Runs
P08 cicd_deployment        ✗ Sub-phase imports fail → CI/CD skipped
P09 observability          ✗ Sub-phase imports fail → monitoring skipped
P10 docs_delivery          ✗ Sub-phase imports fail → docs skipped
P11 deployment             ✓ Runs (runs as root, 0.0.0.0, no network isolation)
```

**Result**: 6 of 11 active pipeline phases produce zero output. Pipeline reports "completed" despite delivering an empty, unsecured, unmonitored application.

## 10.3 The Fix (Highest Priority)

```python
# phases/__init__.py — add these 3 lines at the top:
import sys, pathlib
_legacy = pathlib.Path(__file__).parent / "_legacy"
if str(_legacy) not in sys.path:
    sys.path.insert(0, str(_legacy))
```

This single fix unblocks P04, P06, P07, P08, P09, P10.

---

# 11. CRITICAL FIXES — PIPELINE-BREAKING

These must be fixed first. Until they are fixed, AetherOS produces empty output for most phases.

## FIX-001 🔴 Legacy Import Path Fix (Unblocks 6 phases)
**File**: `phases/__init__.py`  
**Problem**: 22 sub-phase imports fail with ModuleNotFoundError, caught silently  
**Fix**: Add `sys.path.insert(0, str(phases_dir / "_legacy"))` to `phases/__init__.py`  
**Also**: Add `phases/_legacy/__init__.py` (empty file) to make it a package

## FIX-002 🔴 Pipeline.py Two Broken Imports
**File**: `orchestrator/pipeline.py`  
**Problem 1**: `from aether_os.phases.p08_cicd.pipeline import run_repair` → legacy path, crashes `_phase_cicd`  
**Problem 2**: `from core.memory.memory_manager import MemoryManager` → wrong prefix, crashes after successful run  
**Fix**: Change to `from aether_os.phases._legacy.p08_cicd.pipeline import run_repair` and `from aether_os.core.memory.memory_manager import MemoryManager`

## FIX-003 🔴 PIPELINE_EVENTS/CONTROL Cross-Worker Fix
**File**: `orchestrator/events.py`, `orchestrator/factory_pipeline.py`  
**Problem**: In-process dicts invisible across 8 uvicorn workers. SSE and pause/cancel fail 7/8 of the time.  
**Fix**: Replace with Redis pub/sub (see A-001 fix code in Part A)

## FIX-004 🔴 /pipeline/start run_id Mismatch
**File**: `gateway/api.py` lines 605-636  
**Problem**: Endpoint creates one UUID, pipeline.run() creates another. Status check always 404.  
**Fix**: Generate run_id once, pass to pipeline.run() as parameter

## FIX-005 🔴 asyncio.create_task() GC Problem
**File**: `gateway/api.py` lines 624, 828, 1322  
**Problem**: Unreferenced tasks silently GC'd mid-pipeline. Run stays "running" forever.  
**Fix**:  
```python
_background_tasks: set[asyncio.Task] = set()
task = asyncio.create_task(_run_bg())
_background_tasks.add(task)
task.add_done_callback(_background_tasks.discard)
```

## FIX-006 🔴 Mass Assignment Vulnerability — Plan Escalation
**File**: `gateway/api.py` line 848  
**Problem**: `update(Organisation).values(req)` — any user can set `plan=enterprise`  
**Fix**: Whitelist allowed fields; use typed Pydantic model for request body

## FIX-007 🔴 Production Secrets in Git
**File**: `.env`  
**Problem**: JWT secret, admin password, ZT secret committed to repository  
**Fix**:  
1. Rotate all secrets immediately  
2. `echo ".env" >> .gitignore`  
3. `git filter-repo --invert-paths --path .env`  
4. Store in AWS Secrets Manager / HashiCorp Vault in production

## FIX-008 🔴 ProtectHome Blocks Data Directory
**File**: `deploy/aetheros.service` line 49  
**Problem**: `ProtectHome=yes` makes `~/.aether_os/` inaccessible. Every DB op fails.  
**Fix**: Change to `ProtectHome=no` and set `AETHER_DATA_DIR=/var/lib/aetheros`

## FIX-009 🔴 Request Not Imported — Rate Limiting Broken
**File**: `gateway/api.py` line 36  
**Problem**: `Request` missing from FastAPI imports — IP rate limiting broken on login/register  
**Fix**: Add `Request` to the FastAPI import line

## FIX-010 🔴 Cross-Tenant Run Access (No org_id Filter)
**File**: `gateway/api.py` line 1167  
**Problem**: `select(Run).where(Run.id == run_id)` — no org_id check. Any user can access any run.  
**Fix**: Add `Run.org_id == user["org_id"]` to every Run query

## FIX-011 🔴 Memory Save After Pipeline Crash
**File**: `orchestrator/pipeline.py` line 258  
**Problem**: `from core.memory.memory_manager import MemoryManager` — ModuleNotFoundError  
**Fix**: `from aether_os.core.memory.memory_manager import MemoryManager`

## FIX-012 🔴 matcher.py Always Fails to Load
**File**: `core/memory/matcher.py` line 12  
**Problem**: Legacy import path crashes module — `/memory/search` always returns empty  
**Fix**: Update import after FIX-001 is applied

## FIX-013 🔴 _phase_testing Hardcodes `passed: True`
**File**: `orchestrator/pipeline.py` line 493  
**Problem**: Tests never executed. Coverage and pass rates fabricated.  
**Fix**: Execute via Docker subprocess; parse pytest JSON output  
```python
result = await asyncio.to_thread(subprocess.run, [
    "docker", "run", "--rm", "--network=none",
    "-v", f"{project_dir}:/code:ro",
    "python:3.11-slim", "python", "-m", "pytest", "/code/tests/", 
    "--json-report", "--json-report-file=/tmp/report.json"
], capture_output=True, text=True, timeout=120)
```

## FIX-014 🔴 asyncpg Commented Out
**File**: `requirements.txt` line 115  
**Problem**: PostgreSQL crashes at startup — `# asyncpg>=0.29.0` is commented out  
**Fix**: Uncomment and run `pip install asyncpg`

## FIX-015 🔴 audit_log DDL Index Wrong Table Name
**File**: `core/db.py` line 175  
**Problem**: `CREATE INDEX ON audit_logs` (plural) but table is `audit_log` (singular). Index fails silently.  
**Fix**: Change `audit_logs` → `audit_log`

## FIX-016 🔴 Sync Redis Client Blocks Event Loop
**File**: `core/rate_limiter.py` lines 31-32  
**Problem**: `redis.Redis` (sync) used inside `async def` handlers. Each call blocks the event loop.  
**Fix**: Change to `import redis.asyncio as _redis_lib` and await all Redis calls

## FIX-017 🟠 SQLite Survivors — Migrate All to PostgreSQL
Files and migration targets:
- `core/audit/ledger.py` → `Run`, `Event`, `AuditLog` ORM models
- `core/memory/store.py` → `user_learning_patterns` table (new)
- `core/billing.py` → `token_budget_records` table
- `core/approval/store.py` → `decisions` table
- `core/artifact_store.py` → `artifact_embeddings` table
- `gateway/mcp_router.py` → `installed_plugin_records` table
- `orchestrator/factory_pipeline.py` (_update_state, live_url writes) → ORM helpers
- `gateway/api.py` (10 raw sqlite3 calls) → ORM queries

## FIX-018 🟠 factory_pipeline State Machine Uses Wrong Phase Names
**File**: `orchestrator/factory_pipeline.py`  
**Problem**: `PHASE_TO_STATE` dict maps 26 old phase names. Current system has 12.  
**Fix**: Update mapping to new 12 consolidated phase names (p01_intake_requirements through p11_deployment)

## FIX-019 🟠 run_change_request Starts Full New Pipeline
**File**: `orchestrator/factory_pipeline.py` line 484  
**Problem**: Change requests create entirely new projects instead of patching existing ones  
**Fix**: Implement diff-and-patch flow: load existing files, generate only changed components, apply diff

## FIX-020 🟠 Human-in-the-Loop Gate Never Pauses Pipeline
**File**: `orchestrator/factory_pipeline.py` lines 296-301  
**Problem**: `PhaseBase._escalate()` creates ticket but pipeline continues unconditionally  
**Fix**: Check approval ticket status in Redis before proceeding to next phase; wait up to approval timeout

## FIX-021 🟠 Kill Switch Is Pure Stub
**File**: `gateway/api.py` line 2044  
**Problem**: Returns `{"success": True}` without stopping anything  
**Fix**: Set `PIPELINE_CONTROL[run_id] = "cancel"` in Redis; update run status in ORM

## FIX-022 🟠 Admin kill-all Always Returns 0
**File**: `gateway/api.py` line 2049  
**Fix**: Query running runs from ORM; set cancel signal for each; return real count

## FIX-023 🟠 SAML SSO Dead Code
**File**: `gateway/auth_saml.py`  
**Problem**: Flask app, never imported by FastAPI. SAML routes don't exist at runtime.  
**Fix**: Rewrite as FastAPI router using `python-saml`; mount in `create_app()`

## FIX-024 🟠 No JWT Revocation / Logout
**File**: `gateway/auth.py`, `gateway/api.py`  
**Fix**: Add `jti` claim to tokens; implement `/auth/logout` with Redis blacklist; reduce TTL to 8h

## FIX-025 🟠 Login Does Not Check is_active
**File**: `gateway/api.py` line 437  
**Fix**: Add `User.is_active == True` to login query

## FIX-026 🟠 API Keys Hashed with SHA-256 (Not bcrypt)
**File**: `gateway/auth.py` line 36  
**Fix**: Replace `hashlib.sha256` with `bcrypt.hashpw`

## FIX-027 🟠 FastAPI Docs Exposed in Production
**File**: `gateway/api.py` line 315  
**Fix**: `docs_url = None if ENVIRONMENT == "production" else "/docs"`

## FIX-028 🟠 /intelligence/global-insights Unauthenticated
**File**: `gateway/api.py` line 1058  
**Fix**: Add `user: Dict = Depends(get_current_user)` and restrict to admin/owner

## FIX-029 🟠 Trial Run Counter Race Condition
**File**: `gateway/api.py` lines 598-602, 795-799  
**Fix**: Use atomic `UPDATE ... WHERE trial_runs_used < trial_runs_limit ... RETURNING id`

## FIX-030 🟠 Connection Pool Overflow at Scale
**File**: `core/db.py` lines 83-89  
**Fix**: Deploy PgBouncer; reduce per-worker pool to `pool_size=5, max_overflow=10`

## FIX-031 🟠 Generated CORS Wildcard
**File**: `phases/p03_scaffolding/task_agent.py` line 67  
**Fix**: Set CORS origins from context: `cors_origins = [f"https://{domain}"]`

## FIX-032 🟠 Hardcoded JWT Secret in Legacy Module
**File**: `core/identity/identity.py` line 20  
**Fix**: Remove fallback string; raise RuntimeError if env var missing

## FIX-033 🟠 Connection Pool Overflow for 5M Users
**Fix**: Implement PgBouncer in transaction mode. Reduce per-worker pool. Detailed in Section 5.

## FIX-034 🟠 _phase_packaging Stub
**File**: `orchestrator/pipeline.py`  
**Fix**: Implement real tar.gz creation from project directory output

## FIX-035 🟠 Named Agent Registry Empty (14 Agents, 0 Implemented)
**File**: `agents/base.py`  
**Fix**: Implement `CODE_REVIEW`, `SECURITY_ANALYZER`, `TEST`, `FIX_ENGINE` agent classes

## FIX-036 🟠 Missing FK Indexes
**File**: `core/models.py`  
**Fix**: Add `Index("ix_event_run_id", "run_id")` to Event, Snapshot, PhaseCompletion, Decision, Webhook, Workspace models

## FIX-037 🟠 Duplicate Function Names in api.py
**File**: `gateway/api.py`  
**Fix**: Rename or deduplicate `get_preferences` and `update_preferences` (defined twice)

## FIX-038 🟠 FORCE_HTTPS Defaults False
**File**: `gateway/api.py` line 156  
**Fix**: Default to `"true"` in production; enforce in nginx

## FIX-039 🟠 CSP `unsafe-inline` Scripts
**File**: `gateway/api.py` line 151  
**Fix**: Use nonce-based CSP; remove `unsafe-inline`

## FIX-040 🟠 Settings API Writes to .env at Runtime
**File**: `gateway/api.py` lines 1754-1800  
**Fix**: Store API keys in `api_keys` table (encrypted); reload from DB per LLM call

---

# 12. SECURITY VULNERABILITIES — FULL REGISTRY

## Authentication & Session (A-series)

| ID | Severity | Description | File | Status |
|----|----------|-------------|------|--------|
| A-01 | 🔴 CRITICAL | JWT secret in committed .env | `.env` | ⚠ Must rotate |
| A-02 | 🟠 HIGH | No JWT revocation on logout | `gateway/auth.py` | Unfix'd |
| A-03 | 🟠 HIGH | JWT alg=none attack (pin jose version) | `gateway/auth.py:74` | Unfix'd |
| A-04 | 🟠 HIGH | Rate limit bypass via X-Real-IP spoofing | `gateway/api.py:365` | Unfix'd |
| A-05 | 🟠 HIGH | No per-account login lockout | `core/rate_limiter.py` | Unfix'd |
| A-06 | 🔴 CRITICAL | SAML callback — no CSRF, no session creation | `gateway/auth_saml.py:33` | Unfix'd |
| A-07 | 🟡 MEDIUM | API keys SHA-256 (no salt, rainbow table) | `gateway/auth.py:36` | Unfix'd |
| A-08 | 🟡 MEDIUM | JWT in URL for SSE stream | `gateway/api.py:1344` | Unfix'd |

## Injection Attacks (B-series)

| ID | Severity | Description | File | Status |
|----|----------|-------------|------|--------|
| B-01 | 🔴 CRITICAL | Mass assignment on Organisation model | `gateway/api.py:848` | Unfix'd |
| B-02 | 🔴 CRITICAL | Prompt injection in pipeline requirement | `gateway/api.py:563` | Unfix'd |
| B-03 | 🟠 HIGH | Second-order prompt injection via LLM cache | `core/llm/cache.py:31` | Unfix'd |
| B-04 | 🟠 HIGH | Sandbox guard bypass via string obfuscation | `core/sandbox/guard.py:7` | Unfix'd |
| B-05 | 🟠 HIGH | run_pytest executes unvalidated test code | `core/sandbox/guard.py:51` | Unfix'd |
| B-06 | 🟠 HIGH | Template injection in generated main.py | `phases/p03_scaffolding` | Unfix'd |
| B-07 | 🟡 MEDIUM | Log injection via unsanitized user input | `gateway/api.py:606` | Unfix'd |
| B-08 | 🟠 HIGH | SSRF via Ollama health check config | `gateway/api.py:1464` | Unfix'd |
| B-09 | 🟡 MEDIUM | Path traversal in git init cwd | `phases/p03_scaffolding:113` | Unfix'd |
| B-10 | 🟡 MEDIUM | LDAP injection via SAML NameID passthrough | `gateway/auth_saml.py:37` | Unfix'd |

## Access Control (C-series)

| ID | Severity | Description | File | Status |
|----|----------|-------------|------|--------|
| C-01 | 🟠 HIGH | IDOR: changelog endpoint no org_id filter | `gateway/api.py:1167` | Unfix'd |
| C-02 | 🟠 HIGH | IDOR: phase file read no org_id re-validation | `gateway/api.py:997` | Unfix'd |
| C-03 | 🔴 CRITICAL | Vertical privesc via /account/settings | `gateway/api.py:848` | = B-01 |
| C-04 | 🟠 HIGH | IDOR: approve any pipeline decision | `gateway/api.py:654` | Unfix'd |
| C-05 | 🟡 MEDIUM | Unauthenticated global-insights with raw_input | `gateway/api.py:1058` | Unfix'd |
| C-06 | 🟢 LOW | Unauthenticated observability endpoint | `gateway/api.py:1514` | Unfix'd |

## Network & Infrastructure (D-series)

| ID | Severity | Description | File | Status |
|----|----------|-------------|------|--------|
| D-01 | 🟠 HIGH | DNS rebinding against Ollama localhost:11434 | `setup_vps.sh` | Unfix'd |
| D-02 | 🟠 HIGH | Docker socket = host root access | `p11_deployment` | Partial |
| D-03 | 🟠 HIGH | SSRF from generated containers to AetherOS | `p11_deployment:309` | Unfix'd |
| D-04 | 🟡 MEDIUM | Path traversal in file-content endpoint | `gateway/api.py:1659` | Fixed ✓ |
| D-05 | 🟠 HIGH | SSE connections — no rate limit (DoS) | `gateway/api.py:1340` | Unfix'd |
| D-06 | 🟡 MEDIUM | CORS allow_methods=["*"] allow_headers=["*"] | `gateway/api.py:329` | Unfix'd |
| D-07 | 🟡 MEDIUM | HTTP request smuggling (nginx/uvicorn) | `deploy/nginx.conf` | Low risk |
| D-08 | 🟡 MEDIUM | CSP allows unsafe-inline scripts | `gateway/api.py:150` | Unfix'd |

## Denial of Service (E-series)

| ID | Severity | Description | File | Status |
|----|----------|-------------|------|--------|
| E-01 | 🟠 HIGH | Unlimited pipelines when Redis down | `gateway/api.py:624` | Unfix'd |
| E-02 | 🟡 MEDIUM | ReDoS in safe_parse_json regex | `core/llm/client.py:299` | Unfix'd |
| E-03 | 🟡 MEDIUM | PIPELINE_EVENTS queue memory leak | `orchestrator/factory_pipeline.py` | Unfix'd |
| E-04 | 🟡 MEDIUM | Disk exhaustion via project directories | `orchestrator/factory_pipeline.py:145` | Unfix'd |
| E-05 | 🟡 MEDIUM | Slowloris — no keepalive_timeout in nginx | `deploy/nginx.conf` | Unfix'd |
| E-06 | 🟢 LOW | Token budget bypass with enterprise plan (after B-01) | `core/llm/budget.py` | Blocked by B-01 fix |

## Supply Chain (F-series)

| ID | Severity | Description | File | Status |
|----|----------|-------------|------|--------|
| F-01 | 🟠 HIGH | crewai unpinned — no reproducible builds | `requirements.txt:64` | Unfix'd |
| F-02 | 🟠 HIGH | aider-chat executes shell by design | `requirements.txt:67` | Unfix'd |
| F-03 | 🟠 HIGH | Cookiecutter templates from unverified GitHub | `phases/p03_scaffolding:14` | Unfix'd |
| F-04 | 🟡 MEDIUM | gpt-researcher makes outbound web requests | `requirements.txt:105` | Unfix'd |
| F-05 | 🟠 HIGH | Prompt injection → generated code → deployment | Pipeline chain | Unfix'd |

## Secrets & Exfiltration (G-series)

| ID | Severity | Description | File | Status |
|----|----------|-------------|------|--------|
| G-01 | 🟠 HIGH | .env readable via /settings/api-keys endpoint | `gateway/api.py:1727` | Unfix'd |
| G-02 | 🟠 HIGH | LLM cache cross-tenant data leak | `core/llm/cache.py:31` | Unfix'd |
| G-03 | 🟡 MEDIUM | Admin password printed to terminal | `deploy/setup_vps.sh:132` | Unfix'd |
| G-04 | 🟠 HIGH | LangSmith receives all user prompts (GDPR) | `requirements.txt:102` | Unfix'd |
| G-05 | 🟢 LOW | Stack traces in 500 error messages | Multiple | Partial |

## Container & Infrastructure (H-series)

| ID | Severity | Description | File | Status |
|----|----------|-------------|------|--------|
| H-01 | 🟠 HIGH | Generated containers run as root | `p11_deployment:257` | Unfix'd |
| H-02 | 🟡 MEDIUM | Containers restart forever (unless-stopped) | `p11_deployment:309` | Unfix'd |
| H-03 | 🟠 HIGH | ProtectHome=yes conflicts with data dir | `aetheros.service:51` | Unfix'd |
| H-04 | 🟠 HIGH | Ollama exposed to internet (0.0.0.0:11434) | `setup_vps.sh:47` | Unfix'd |
| H-05 | 🟡 MEDIUM | Container name collision (8-char UUID prefix) | `p11_deployment:81` | Unfix'd |

## Frontend Attacks (I-series)

| ID | Severity | Description | File | Status |
|----|----------|-------------|------|--------|
| I-01 | 🔴 CRITICAL | Stored XSS via generated HTML preview | `gateway/api.py:1437` | Unfix'd |
| I-02 | 🟠 HIGH | CSRF protection missing (future cookie risk) | All state endpoints | Low risk now |
| I-04 | 🟢 LOW | Open redirect via HTTPS middleware | `gateway/api.py:153` | Unfix'd |

## LLM-Specific (J-series)

| ID | Severity | Description | File | Status |
|----|----------|-------------|------|--------|
| J-01 | 🟠 HIGH | Max token DoS — 8192 tokens per call × 11 phases | `core/llm/client.py:335` | Unfix'd |
| J-02 | 🟠 HIGH | System prompt extraction via LLM | `core/llm/client.py:85` | Unfix'd |
| J-03 | 🔴 CRITICAL | LLM-generated malicious code auto-deployed | Pipeline chain | Unfix'd |
| J-04 | 🟠 HIGH | Ollama model poisoning (unsigned models) | `setup_vps.sh:47` | Unfix'd |
| J-05 | 🟡 MEDIUM | Cross-user context pollution via shared dict | `orchestrator/factory_pipeline.py:154` | Unfix'd |

## Additional Critical (K-series)

| ID | Severity | Description | File | Status |
|----|----------|-------------|------|--------|
| K-01 | 🟠 HIGH | API keys written to .env at request time | `gateway/api.py:1754` | Unfix'd |
| K-02 | 🟠 HIGH | SSH MITM via paramiko AutoAddPolicy | `core/sandbox/manager.py:366` | Unfix'd |
| K-03 | 🟠 HIGH | builtins.__import__ monkey-patching race | `p11_deployment:186` | Unfix'd |
| K-04 | 🟠 HIGH | Trial run counter TOCTOU race | `gateway/api.py:577` | Unfix'd |
| K-05 | 🟠 HIGH | Webhook URL SSRF | `core/models.py:151` | Unfix'd |
| K-06 | 🟡 MEDIUM | SQLite bypasses ORM WAL consistency | `gateway/api.py:978` | Fix via migration |
| K-07 | 🟡 MEDIUM | No size validation on preview HTML | `gateway/api.py:1442` | Unfix'd |

---

# 13. API STUBS & INCOMPLETE ENDPOINTS

| ID | Endpoint | Problem | Fix |
|----|---------|---------|-----|
| B-002 | `POST /factory/runs/{run_id}/kill` | Returns `{"success": True}` — does nothing | Set Redis cancel signal, update ORM status |
| B-003 | `POST /admin/kill-all` | Always returns `killed_count: 0` | Query running runs, set cancel for each |
| B-004 | `GET /webhooks` | Always returns `[]` | Query Webhook model by org_id |
| B-005 | `POST /webhooks` | Returns hardcoded `{"id": "w_1"}` | Persist to Webhook ORM + SSRF validation |
| B-006 | `DELETE /webhooks/{webhook_id}` | Always returns `{"success": True}` | Delete with org_id check |
| B-007 | `GET /marketplace/profiles` | Returns `[]`, no auth | Read MarketplaceProfile + auth |
| B-008 | `POST /marketplace/publish` | No DB write | Insert MarketplaceProfile |
| B-009 | `GET /account/projects` | Always returns `[]` | Query runs grouped by project |
| B-010 | `GET /account/projects/search` | Always returns `[]` | Full-text search on raw_input |
| B-011 | `GET /intelligence/quality-benchmark` | Hardcoded scores (92.5, 90.0) | Aggregate from real test results |
| B-012 | `GET /system/health` | Hardcoded values | Real DB + Redis health checks |
| B-013 | `GET /compliance/org-report` | Returns zeros | Aggregate from Run model |
| B-015 | Human-in-the-loop gate | Never pauses pipeline | Redis-based approval wait loop |
| B-016 | `_phase_testing()` | Hardcodes `passed: True` | Execute real tests via Docker |
| B-017 | Autonomous mode | Hardcodes test results | Real test execution |
| B-018 | Agent registry | 14 declared, 0 implemented | Implement CODE_REVIEW, SECURITY, TEST, FIX |
| B-021 | `run_change_request()` | Starts full new pipeline | Implement diff-and-patch flow |
| B-022 | State machine phase names | 26 old names, 12 actual | Update PHASE_TO_STATE mapping |
| B-023 | CI webhook router | Import fails, route never mounts | Fix import path |
| B-024 | Settings API key storage | Writes to .env file | Store in api_keys DB table |
| B-025 | Generated CORS | `allow_origins=["*"]` wildcard | Use domain-specific origins |
| B-026 | Duplicate function names | get_preferences defined twice | Deduplicate |
| B-027 | Pricing endpoint | Hardcoded HTML | Dynamic pricing from config |

**New endpoints to implement:**
```python
POST /factory/runs/{run_id}/frontend-spec
GET  /factory/runs/{run_id}/frontend-spec
POST /factory/runs/{run_id}/backend-spec
GET  /factory/runs/{run_id}/backend-spec
POST /factory/runs/{run_id}/validate-spec
POST /auth/logout
GET  /account/data-export           # GDPR Article 20
DELETE /account                     # GDPR Article 17
GET  /compliance/ai-registry        # EU AI Act Article 51
POST /marketplace/install/:id
GET  /api/notifications
POST /api/notifications/{id}/read
POST /auth/forgot-password
PUT  /api/account/profile
POST /api/auth/change-password
GET  /scim/v2/Users                 # SCIM 2.0
POST /scim/v2/Users
GET  /scim/v2/Users/{id}
PUT  /scim/v2/Users/{id}
PATCH /scim/v2/Users/{id}
DELETE /scim/v2/Users/{id}
GET  /audit/logs/export?format=csv
```

---

# 14. FRONTEND BUGS & MISSING UI

## Critical Frontend Bugs

| ID | File | Problem | Fix |
|----|------|---------|-----|
| C-001 | `DecisionsPanel.jsx:11,32` | `api.get()` / `api.post()` — TypeError on mount | Change to `api.client.get()` / `api.client.post()` |
| C-002 | `Marketplace.jsx:116` | Install button has no onClick handler | Add handler + implement `/marketplace/install/:id` |
| C-003 | `ClientPortal.jsx:143` | Hardcoded payroll demo data | Replace with real project data from API |
| C-004 | `Compliance.jsx:64` | Light-theme classes in dark app | Replace with dark theme tokens |
| C-005 | `Compliance.jsx:86` | `run.id` should be `run.run_id` — all IDs show "undefined" | Use `run.run_id \|\| run.id` |
| C-006 | `ProjectView.jsx:427` | SSE has no reconnect strategy | Exponential backoff reconnect |
| C-017 | `ProjectView.jsx:1001` | `feedLines.map()` uses index as key — O(n) re-renders | Use unique id per line |
| C-023 | `Dashboard.jsx:133` | "NEW PIPELINE" navigates to `/new` (wrong route) | Change to `/new-project` |

## Missing Pages (Must Build)

| Page | Path | Description |
|------|------|-------------|
| Prompt Input Tab | `/prompt` | Conversation-style project intake (Section 8) |
| Frontend Builder | `/frontend-builder` | Visual frontend spec designer (Section 6) |
| Backend Builder | `/backend-builder` | Schema/API designer (Section 7) |
| Admin User Management | `/admin/users` | User list, roles, deactivate, invite |
| User Profile | `/profile` | Name, avatar, password change |
| Webhook Management | `/settings/webhooks` | List, add, edit, delete webhooks |
| 404 Page | `*` | Replace redirect with proper 404 |
| SSO Login Button | `Login.jsx` | "Sign in with SSO" → `/api/auth/saml/login` |

## Missing UI Features

| ID | Problem | Fix |
|----|---------|-----|
| C-007 | No Admin User Management page | Create `AdminUsers.jsx` |
| C-008 | No role-based UI differentiation | Add role context; hide admin controls for non-admins |
| C-009 | No SSO login option | Add SSO button to Login page |
| C-010 | 4 independent polling loops for same endpoint | Shared `RunsContext` with single interval |
| C-011 | No pagination on any list view | Add page/limit params; pagination UI |
| C-012 | Zero ARIA labels | Add aria-label to all icon buttons |
| C-013 | No mobile responsive layout | Add hamburger menu + responsive Sidebar |
| C-014 | Light theme components in dark app (multiple) | Global token replacement |
| C-015 | `tailwind.config.js` ignored by Tailwind v4 | Delete it; config belongs in `index.css @theme` |
| C-016 | SSE terminal capped at 300 lines, no notice | Add warning banner |
| C-018 | Model picker only shows Ollama | Dynamic list from connected providers |
| C-019 | ErrorBoundary RETRY can crash-loop | Fix with retry key state |
| C-021 | Compliance and Marketplace missing from sidebar | Add nav entries |
| C-022 | No forgot password link | Implement `POST /auth/forgot-password` + UI |
| C-025 | CostDashboard missing `$` prefix | Fix format string |
| C-026 | Color contrast fails WCAG AA | Fix `--color-muted` to `#718096` |
| C-033 | No in-app notification system | Implement notification center |
| C-034 | No run history search/filter | Add filter controls + API params |
| C-036 | No user profile/password change page | Create `/profile` route |
| C-037 | No audit log export | Add CSV export button + API endpoint |
| C-038 | No webhook management UI | Create WebhookSettings component |
| C-039 | Kill switch has no UI | Add Force Kill button in ProjectView for admins |
| C-042 | Hardcoded dark theme only | Add theme toggle; store in preferences |
| C-045 | No org switcher | Add switcher for multi-org users |

---

# 15. LEGAL, REGULATORY & COMPLIANCE GAPS

| ID | Standard | Problem | Fix |
|----|---------|---------|-----|
| D-001 | Contract Law | No ToS, EULA, or DPA | Draft documents; add `/legal/*` routes |
| D-002 | GDPR Art. 17 | No right to erasure endpoint | Implement `DELETE /account` |
| D-003 | GDPR Art. 20 | No data portability | Implement `GET /account/data-export` |
| D-004 | GDPR Art. 13 | No consent capture at registration | Add `privacy_policy_accepted: bool` to RegisterRequest |
| D-005 | GDPR Art. 44 | LangSmith tracing ON by default → prompts leave EU | Set `LANGCHAIN_TRACING_V2=false` as default |
| D-006 | EU AI Act Art. 13 | Risk classification hardcoded "Medium Risk" | Connect compliance engine to UI |
| D-007 | SOC 2 | No backup/disaster recovery plan | Add `deploy/backup.sh` + pg_dump cron |
| D-008 | Contractual | SLA promised in pricing but never measured | Integrate uptime monitoring; add `/api/system/sla` |
| D-009 | Enterprise IT | No SCIM 2.0 user provisioning | Implement SCIM 2.0 endpoints |
| D-010 | OWASP A05 | FastAPI docs exposed in production | Disable in production |
| D-011 | GDPR Art. 44 | Data residency hardcoded as `us-east-1` | Make dynamic from env var |
| D-012 | ISO 27001 | No audit log of failed logins, 403s, 429s | Log all security events to audit_log table |
| D-013 | ISO 27001 | Account lockout by IP only (not email) | Add per-email lockout in Redis |
| D-014 | ISO 27001 | No idle session timeout | Add `last_active` to JWT; check on each request |
| D-015 | RBAC | viewer role indistinguishable from member | Enforce capability matrix in all routes |
| D-016 | EAR/ITAR | Export control check never enforced as gate | Make mandatory gate before P03 |
| D-017 | ISO 27001 | Hardcoded fallback JWT secret in identity.py | Remove fallback; raise RuntimeError |
| D-018 | SOC 2 | FORCE_HTTPS defaults False | Default True in production |
| D-019 | OWASP A05 | unsafe-inline in CSP | Nonce-based CSP |
| D-020 | GDPR Art. 32 | PII stored in plaintext (email, IP) | EncryptedString TypeDecorator with AES-256-GCM |
| D-021 | EU AI Act Art. 51 | No AI system registry | Create `ai_system_registry` table; populate on deploy |
| D-022 | GDPR Art. 5(1)(e) | No data retention policy | Add cleanup job; `DATA_RETENTION_DAYS=365` env var |
| D-023 | OWASP A03 | User input not sanitized for prompt injection | Sanitize `raw_input` before LLM injection |
| D-024 | OWASP A06 | python3-saml XXE risk | Pin to latest version; enable defusedxml |

---

# 16. ATTACK VECTOR REGISTRY (52 VECTORS)

Full penetration test results. All vectors catalogued in `MASTER_SECURITY_AND_HARDENING_REPORT.md` Sections A–K. Summary of top 10 immediate threats:

1. **A-01** — JWT secret committed to git → forge any user token (CRITICAL, difficulty 1)
2. **B-01 / C-03** — Mass assignment → any user gets enterprise plan free (CRITICAL, difficulty 1)
3. **B-02 / J-03** — Prompt injection → deploy malicious code to end users (CRITICAL, difficulty 2)
4. **I-01** — Stored XSS via generated preview HTML → steal any JWT (CRITICAL, difficulty 3)
5. **K-04** — Trial run TOCTOU → unlimited free runs (HIGH, difficulty 2)
6. **G-02** — LLM cache cross-tenant leak of business requirements (HIGH, difficulty 3)
7. **H-04** — Ollama exposed on 0.0.0.0:11434 — no auth, compute theft (HIGH, difficulty 1)
8. **D-03** — Generated containers SSRF into AetherOS internals (HIGH, difficulty 3)
9. **B-04 / B-05** — Sandbox guard bypassed via import obfuscation → host RCE (HIGH, difficulty 2)
10. **A-04** — IP header spoofing → unlimited brute force (HIGH, difficulty 1)

---

# 17. INFRASTRUCTURE FAILURE MODES (47 SCENARIOS)

Full chaos engineering analysis in `MASTER_SECURITY_AND_HARDENING_REPORT.md` Parts F (infrastructure), B (pipeline), C (concurrency), D (data), E (resource), F (error handling), G (generated code), H (operational). Key scenarios:

| ID | Trigger | Impact | Fix |
|----|---------|--------|-----|
| A-04 | Disk fills with project dirs | Runs show "completed" with empty output — SILENT | Add disk check before pipeline; cleanup job |
| H-08 | Multi-worker PIPELINE_EVENTS | SSE, pause, cancel fail 7/8 runs | Redis pub/sub |
| A-02 | Redis unavailable at startup | Rate limits × 8 (per-worker, not global) | Require Redis in production |
| B-02 | Malformed JSON from LLM | Security phase silently passes broken code | Treat parse_error as security failure |
| F-01 | init_db() failure logged as WARNING | App starts with no tables → 500 on first request | Change to sys.exit(1) |
| E-04 | Anthropic client created per call | File descriptor exhaustion at 80K users | Cache client as module-level singleton |
| H-06 | Crash recovery full table scan | Startup takes minutes at scale | Add time bound + index on (status, started_at) |
| H-05 | JWT secret rotation | All 80K users logged out simultaneously | Support two simultaneous secret keys during rotation |
| A-05 | OOM kills uvicorn worker | In-flight runs become zombies | Cap accumulated_context; set memory ulimits |
| F-04 | Rate limiter exception | Fail-open: unlimited requests while Redis down | Fail-closed on exception |

---

# 18. INCOMPLETE & INTERRUPTED WORKFLOWS

## 18.1 Pipeline Phases With Incomplete Implementation

| Phase | File | Incomplete Work |
|-------|------|----------------|
| P07 Testing | `orchestrator/pipeline.py:493` | `passed: True` hardcoded — tests never run |
| P07b Self-Healing | `phases/p07b_self_healing/task_agent.py:91` | No backup before overwrite; JS/TS not validated |
| P08 CI/CD | `phases/p08_cicd_deployment/` | All sub-phase imports fail → CI/CD skipped |
| P09 Observability | `phases/p09_observability/` | All sub-phase imports fail → monitoring skipped |
| P10 Docs | `phases/p10_docs_delivery/` | All sub-phase imports fail → docs skipped |
| P11 Deployment | `phases/p11_deployment/task_agent.py` | Runs as root; 0.0.0.0; no network isolation |
| Packaging | `orchestrator/pipeline.py` | Returns fake .tar.gz name — no actual archive |
| Autonomous mode | `orchestrator/pipeline.py:239` | Hardcodes `tests_passed=10, coverage_percent=85` |

## 18.2 Plugin System (10 Skills — All Unimplemented)

**File**: `core/plugins/skills.py`  
All 10 skill implementations have `pass` body. The skill system is wired in the UI but executes nothing. Skills to implement:
1. `CodeReviewSkill` — automated code quality review
2. `SecurityScanSkill` — bandit + semgrep wrapper
3. `TestGenerationSkill` — generate test cases from code
4. `DocumentationSkill` — generate docstrings and README
5. `RefactorSkill` — LLM-driven refactoring
6. `PerformanceSkill` — profiling and optimization
7. `MigrationSkill` — database migration generation
8. `APISpecSkill` — OpenAPI spec generation
9. `DeploymentSkill` — infrastructure as code generation
10. `MonitoringSkill` — alert and dashboard configuration

## 18.3 Connector System (All Unimplemented)

**File**: `core/plugins/connectors.py`  
Base class has `pass` body. 17 connectors declared in ConnectorHub UI but none functional:
GitHub, GitLab, Jira, Linear, Slack, Teams, Notion, Confluence, AWS, GCP, Azure, Vercel, Railway, Supabase, PlanetScale, Stripe, SendGrid.

## 18.4 Change Request Workflow

**Current**: `run_change_request()` starts a completely new pipeline from scratch  
**Required**: Diff-and-patch workflow:
1. Load existing project from storage
2. Generate only the components that changed
3. Apply git-style patch
4. Run self-healing on changed files only
5. Re-run P06 security review
6. Deploy updated version

## 18.5 Agent Mesh (14 Agents Declared, 0 Implemented)

**File**: `agents/base.py`  
`AgentName` enum has 14 entries. `default_agent_registry` never populated. The agent orchestration layer is decorative. Minimum to implement: `CODE_REVIEW`, `SECURITY_ANALYZER`, `TEST_RUNNER`, `FIX_ENGINE`.

---

# 19. COST REDUCTION STRATEGY

## Current State: ~$2.73/run → Target: $0.35/run

| Mechanism | Savings | Implementation |
|-----------|---------|----------------|
| Anthropic prompt caching | ~$1.50/run (55%) | Cache system prompts (`cache_control: ephemeral`) — already in client.py |
| Context compression (Haiku) | ~$0.60/run (22%) | Compress accumulated context before each phase with Haiku |
| LLM response cache | ~$0.40/run (15%) | Cache identical task_type+prompt combos — include org_id in key |
| Token budget manager | ~$0.20/run (7%) | Hard cap at 85% budget; downgrade to Haiku for final phases |
| Phase parallelization | No cost savings but faster | Run P09+P10 in parallel; P05 overlaps with P04 review |
| Smart model selection | ~$0.03/run per phase | Use Haiku for simple tasks (doc generation, changelog); Sonnet for code |

## Prompt Caching Implementation

```python
# core/llm/client.py — use Anthropic cache_control on system prompts
messages = [
    {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"}  # Cache this for 5 minutes
            },
            {
                "type": "text", 
                "text": user_prompt
            }
        ]
    }
]
```

## Context Compressor

```python
# core/llm/compressor.py
async def compress_context(accumulated_context: dict, max_tokens: int = 4000) -> str:
    """Use Haiku to compress accumulated phase outputs to stay within budget."""
    full_context = json.dumps(accumulated_context)
    if len(full_context) < max_tokens * 4:
        return full_context
    
    summary = await call_llm(
        model="claude-haiku-4-5-20251001",  # Cheapest model for compression
        prompt=f"Summarize the key decisions from this pipeline context in under 1000 tokens:\n{full_context[:20000]}",
        task_type="compress"
    )
    return summary
```

---

# 20. HARDENING CHECKLIST (100/100 BENCHMARK)

## Network Layer
- [ ] TLS 1.3 only (disable TLS 1.2 and below)
- [ ] HSTS with `max-age=31536000; includeSubDomains; preload`
- [ ] DNSSEC enabled on domain
- [ ] DDoS protection (Cloudflare or equivalent) in front of nginx
- [ ] Rate limiting at nginx level (not just application level)
- [ ] Fail2ban for SSH and nginx
- [ ] Non-standard SSH port + key-only auth
- [ ] Firewall: only ports 22, 80, 443 open
- [ ] Ollama bound to 127.0.0.1 only (`OLLAMA_HOST=127.0.0.1`)
- [ ] `ufw deny 11434` to block external Ollama access
- [ ] nginx keepalive_timeout, client_header_timeout, send_timeout configured

## Application Layer
- [ ] All API keys rotated; stored in secrets manager
- [ ] JWT expiry ≤ 8 hours; refresh token flow implemented
- [ ] Token blacklist (jti + Redis) implemented
- [ ] All sync DB calls wrapped in `asyncio.to_thread()`
- [ ] `asyncpg` installed and uncommented in requirements.txt
- [ ] PgBouncer deployed for connection pooling
- [ ] Redis required in production; fail-closed on Redis errors
- [ ] Mass assignment vulnerability fixed (`/account/settings`)
- [ ] All `except: pass` replaced with explicit error handling and logging
- [ ] Background task references stored in `_background_tasks` set
- [ ] `org_id` added to all Run, PhaseCompletion, RunMetadata queries
- [ ] LLM cache includes `org_id` in cache key
- [ ] Rate limiter fail-closed (deny on Redis error)
- [ ] `FORCE_HTTPS=true` default in production
- [ ] FastAPI docs disabled in production
- [ ] `.env` removed from git history and added to .gitignore

## Pipeline Layer
- [ ] `phases/__init__.py` sys.path fix for `_legacy/` imports
- [ ] 22 broken sub-phase imports resolved
- [ ] `asyncio.create_task()` references tracked in `_background_tasks` set
- [ ] `PIPELINE_EVENTS`/`CONTROL` migrated to Redis pub/sub
- [ ] Human-in-the-loop gate actually pauses pipeline (Redis approval wait)
- [ ] Kill switch implemented (not stub)
- [ ] `_phase_testing()` runs real tests via Docker
- [ ] Generated code scanned before deployment (bandit + semgrep mandatory gate)
- [ ] Generated code uses domain-specific CORS origins (not wildcard)
- [ ] Generated Docker containers run as non-root user (UID 1001)
- [ ] Generated containers bound to 127.0.0.1, not 0.0.0.0
- [ ] Generated containers use `--network=aetheros-isolated`
- [ ] Project directory cleanup job runs daily

## Security Headers
- [ ] `Content-Security-Policy`: no `unsafe-inline`, nonce-based
- [ ] `X-Frame-Options: DENY`
- [ ] `X-Content-Type-Options: nosniff`
- [ ] `Referrer-Policy: strict-origin-when-cross-origin`
- [ ] `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- [ ] `X-XSS-Protection: 1; mode=block`
- [ ] `Strict-Transport-Security: max-age=31536000; includeSubDomains`

## Authentication
- [ ] SAML 2.0 SSO fully implemented as FastAPI router
- [ ] SCIM 2.0 provisioning endpoints implemented
- [ ] MFA (TOTP) available for admin/owner roles
- [ ] Account lockout: 5 failures → 15min lock, per email AND per IP
- [ ] Idle session timeout (30 min)
- [ ] No JWT in URLs (remove legacy SSE `?token=` path)
- [ ] API keys hashed with bcrypt (not SHA-256)
- [ ] Login checks `User.is_active == True`
- [ ] `/auth/logout` endpoint implemented with token blacklist
- [ ] JWT secret rotation with two-key support (prevent mass logout)

## Compliance
- [ ] Privacy Policy linked at registration; consent timestamp stored
- [ ] GDPR erasure endpoint (`DELETE /account`) implemented
- [ ] GDPR data export endpoint (`GET /account/data-export`) implemented
- [ ] Audit log of all security events (failed logins, 403s, 429s)
- [ ] Data retention policy enforced (`DATA_RETENTION_DAYS=365`)
- [ ] LangSmith tracing opt-in only (default: `LANGCHAIN_TRACING_V2=false`)
- [ ] ToS/EULA/DPA documents exist at `/legal/*`
- [ ] Export control check enforced as pipeline gate before P03
- [ ] AI system registry populated on each deployment
- [ ] PII encrypted at rest (email, IP address) using AES-256-GCM

## Monitoring
- [ ] Structured JSON logging (not plain text)
- [ ] Error alerting (Sentry or equivalent)
- [ ] Uptime monitoring with SLA measurement
- [ ] Database backup: daily `pg_dump`, 30-day retention, stored off-site
- [ ] Disk usage alerts at >80% threshold
- [ ] Dependency vulnerability scanning (`pip-audit` in CI/CD)
- [ ] Prometheus metrics + Grafana dashboards
- [ ] Alert on: pipeline failure rate >5%, P99 latency >10s, error rate >1%

---

# 21. FIX PRIORITY ORDER — SEQUENCED EXECUTION PLAN

## Tier 0 — Fix Before Any Other Work (Blocks Everything Else)

1. **FIX-007**: Rotate all secrets in `.env`. Remove from git history. This is a live security incident.
2. **FIX-001**: Add `sys.path.insert` to `phases/__init__.py`. This unblocks P04, P06, P07, P08, P09, P10 — 6 of 11 phases are currently producing zero output.
3. **FIX-014**: Uncomment `asyncpg` in requirements.txt. Service crashes at boot without this.
4. **FIX-008**: Fix `ProtectHome=yes` in systemd service. Service crashes on every DB op.

## Tier 1 — Security Critical (Fix Before Any User Traffic)

5. **FIX-006** (B-01/C-03): Mass assignment vulnerability — any user can set plan=enterprise
6. **FIX-010**: Add org_id filter to all Run queries (IDOR cross-tenant access)
7. **FIX-003**: Migrate PIPELINE_EVENTS/CONTROL to Redis (SSE/pause/cancel work)
8. **FIX-004**: Fix /pipeline/start run_id mismatch (status always 404)
9. **FIX-005**: Store asyncio.create_task() references (prevent GC mid-pipeline)
10. **FIX-009**: Add `Request` import (rate limiting broken on login/register)
11. **B-02**: Sanitize `raw_input` before injecting into LLM prompts
12. **G-02**: Add `org_id` to LLM cache key (cross-tenant data leak)
13. **K-04**: Atomic trial run counter (TOCTOU race)
14. **H-04**: Block Ollama on firewall: `ufw deny 11434`; bind to `OLLAMA_HOST=127.0.0.1`

## Tier 2 — Production Readiness

15. **FIX-017**: Migrate all SQLite survivors to PostgreSQL ORM
16. **FIX-002**: Fix two broken imports in orchestrator/pipeline.py
17. **FIX-012**: Fix matcher.py legacy import
18. **FIX-013**: Wire real test execution in `_phase_testing()`
19. **FIX-016**: Make Redis client async in rate_limiter.py
20. **FIX-015**: Fix audit_log DDL index name (audit_logs → audit_log)
21. **FIX-020**: Implement human-in-the-loop gate (Redis approval wait)
22. **FIX-021**: Implement real kill switch
23. **FIX-023**: Rewrite auth_saml.py as FastAPI router
24. **FIX-024**: Implement /auth/logout with JWT blacklist
25. **FIX-025**: Add is_active check to login query
26. **FIX-026**: Migrate API key hashing to bcrypt
27. **FIX-027**: Disable FastAPI docs in production
28. **FIX-028**: Add auth to /intelligence/global-insights
29. **FIX-030**: Deploy PgBouncer; fix connection pool settings
30. **FIX-036**: Add missing FK indexes

## Tier 3 — Feature Completion

31. Implement all 25 stub API endpoints (Section 13)
32. Fix all critical frontend bugs (C-001 through C-006)
33. Build missing pages: AdminUsers, Profile, WebhookSettings, 404
34. Implement SSO login button in Login.jsx
35. Add role-based UI differentiation
36. Fix all GDPR compliance gaps (D-001 through D-004)
37. Implement per-user isolated learning loop (Section 4)
38. Build Frontend Builder tab (Section 6)
39. Build Backend Builder tab (Section 7)
40. Build Prompt Input tab (Section 8)

## Tier 4 — Scale & Excellence

41. Implement SCIM 2.0 provisioning
42. Add MFA for admin/owner roles
43. Implement plugin system (10 skills, 17 connectors)
44. Move pipeline to separate worker pool (Celery/ARQ)
45. Deploy Kubernetes with HPA (auto-scaling to 5M users)
46. Implement PgBouncer in transaction mode
47. Add Prometheus metrics + Grafana dashboards
48. Implement nonce-based CSP
49. Add data encryption at rest (AES-256-GCM for PII)
50. Add AI system registry (EU AI Act compliance)

---

# APPENDIX: SEVERITY COUNTS

| Severity | Architecture | API Stubs | Frontend | Legal | Security | Total |
|----------|-------------|-----------|---------|-------|---------|-------|
| 🔴 CRITICAL | 9 | 4 | 7 | 4 | 7 | **31** |
| 🟠 HIGH | 13 | 14 | 10 | 11 | 28 | **76** |
| 🟡 MEDIUM | 5 | 9 | 18 | 9 | 17 | **58** |
| 🟢 LOW | 0 | 0 | 10 | 0 | 6 | **16** |
| **Total** | **27** | **27** | **45** | **24** | **58** | **181** |

Plus 52 attack vectors and 47 failure modes = **280+ total findings**.

---

*Compiled: 2026-05-10 | Source: Live session audit + MASTER_SECURITY_AND_HARDENING_REPORT.md (Parts A–F + Appendix)*  
*Target: 5 million concurrent users, zero vulnerabilities, per-user isolated learning loop, hyper-defensible generated code*
