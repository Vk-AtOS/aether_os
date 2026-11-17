# 02 Call flow: start a factory run

One real request end to end: `POST /api/factory/start` (`gateway/routers/factory_start_router.py:124`), then the background run, then the event stream back to the dashboard. A second, small diagram shows a dashboard call proxied to Velaris.

## 2a. Start of a factory run

```mermaid
sequenceDiagram
  autonumber
  participant B as Browser dashboard
  participant N as nginx
  participant M as Starlette middleware stack
  participant D as get_current_user dependency
  participant H as start_factory_run handler
  participant R as Redis
  participant P as PostgreSQL
  participant T as asyncio task or SQS consumer
  participant F as FactoryPipeline
  participant L as ModelRouter
  participant X as LLM provider
  participant S as Project dir, S3

  B->>N: POST /api/factory/start with JWT bearer
  N->>N: limit_req zone api, 600 per min per IP, burst 100
  N->>M: proxy_pass to 127.0.0.1:8000
  Note over M: outermost to innermost: audit log, Prometheus, TraceId, GZip, CORS, HTTPS redirect, security headers, org id logging, strip /api prefix
  M->>D: route matched, dependency runs
  D->>R: revocation check, jwt blacklist and family keys
  D->>P: load user and org, active, email verified, must change password
  D->>D: role from DB row, then check_role, then admin MFA check
  D->>R: per user and per org rate window, 503 if Redis is down in production
  D->>H: claims dict
  H->>P: policy facts, then evaluate run.start, denial is written to ledger
  H->>R: factory start rate checks, per minute, per hour, concurrent runs
  H->>P: org row, storage limit check, 402 over the limit
  H->>H: prompt guard on raw_input
  H->>R: org start lock, SET NX with 20 s TTL
  H->>P: policy again plus atomic trial run consume
  H->>P: insert Run row, status queued
  alt SQS_QUEUE_URL is set and send succeeds
    H->>T: message to SQS, gateway consumer polls the queue
  else default
    H->>T: asyncio.create_task in the same worker process
  end
  H-->>B: 200 run_id, status started or queued
  M->>P: after response, audit_log row and audit_chain entry for POST /factory/start
  T->>L: council pre flight, 60 s cap, may skip
  T->>F: factory.run holds a pipeline semaphore slot, 30 min timeout
  F->>P: run status running
  loop each stage wave in PHASE_SEQUENCE
    F->>L: LLM calls from stage supervisors
    L->>P: admit, kill switch, plan, monthly USD and token cap
    L->>X: HTTPS call, fallback chain on failure
    L->>P: record token usage
    F->>S: write generated files to project dir
    F->>P: save checkpoint on the run row
    F->>R: publish event, history list, pipeline events table
    F->>R: read control flag, cancel or pause
  end
  F->>P: status council_review, then completion tasks
  F->>S: embed artifacts, upload to S3 if S3_BUCKET is set
  B->>N: POST sse-token, then GET stream with sse_token
  N->>M: stream route, limit_req zone sse
  M->>R: pop one time sse token, subscribe pipeline events channel
  R-->>B: server sent events, replay of history first
```

## 2b. Dashboard call proxied to Velaris

```mermaid
sequenceDiagram
  autonumber
  participant B as Browser dashboard
  participant G as Gateway velaris proxy
  participant P as PostgreSQL
  participant A as Audit chain
  participant V as Velaris API Verifier
  participant C as Velaris access and services

  B->>G: request with JWT, no org or user in body
  G->>G: get_current_user, API keys are refused for Velaris
  G->>P: identity from the user row, org role
  G->>G: refuse body keys org_id, actor, approved_by, reviewed_by
  G->>A: append velaris action BEFORE the call, ids and field names only
  G->>V: HTTP with 4 signed headers
  Note over G,V: HMAC SHA256 over method, path and query, timestamp, nonce, body hash, identity hash. Identity is an Ed25519 signed claim set, 60 s TTL, nonce equal to the request nonce
  V->>V: compare HMAC, 60 s window, nonce used once, verify Ed25519, check iss and aud
  V->>C: Caller id, org, roles
  C->>C: org must equal VELARIS_ORG, then role and data category rules
  C-->>G: JSON, or error with code and message
  G->>A: append result entry, outcome
  G-->>B: JSON, only error code and message of a Velaris error is relayed
```

Derived from:

- Handler order: `gateway/routers/factory_start_router.py:146` (policy), `:150-166` (rate limits), `:169-185` (org and storage), `:241-244` (prompt guard), `:249-250` (start lock and second policy check with trial consume), `:256-272` (Run insert, status `queued`), `:277-321` (SQS), `:323-353` (`asyncio.create_task`).
- Middleware order: registration order in `gateway/api.py`: `strip_api_prefix` `:112`, OrgIDLogging `:123`, SecurityHeaders `:124`, HttpsRedirect `:125`, CORS `:130`, GZip `:138`, TraceId `:140`, Prometheus `:146-150`, audit log `:160`. Starlette puts the last added outermost (comment at `:137`). This order is derived from that rule, not observed in a running app. There is no rate limit middleware, no role middleware and no policy middleware.
- Auth dependency order: `gateway/dependencies.py:50` (decode), `:52` (MFA pending), `:60` (revocation, `gateway/auth_refresh.py:108-136`, 503 if Redis cannot answer), `:68-95` (user, org, email, forced password change), `:99` (plan from org row), `:102` (role from DB, so a demoted admin loses rights at once), `:105` (`check_role`, `gateway/role_gate.py:66-79`), `:106` (`check_admin_mfa`), `:107` (`enforce_api_rate`, `core/api_rate_limit.py:50-69`).
- Policy: `gateway/policy_guard.py:32-49`, `core/policy/enforce.py:63-113`, rules `core/policy/rules.py:53,99-131`. Denials are ledgered at `core/policy/enforce.py:53-60`. Fail closed: `:68-70`.
- Factory start rate limits and concurrent runs: `core/rate_limiter.py` (called at `factory_start_router.py:150-166`). Start lock: `core/start_lock.py:21,29-63`.
- Spend cap: not checked at start. It is checked per LLM call in `core/llm/guard.py:41-76` (kill switch, org policy, `check_budget` with projected cost) and called from `core/model_router.py:146`. Usage is recorded at `core/model_router.py:329-336,395`. Budget code: `core/llm/budget.py:133-190`.
- Background execution: default is an in-process `asyncio.create_task` kept in a strong reference set (`factory_start_router.py:101,323,352`). Run function: `gateway/routers/factory_run_background.py:228-343` (council pre flight `:262-300`, `factory.run` `:303`, post build hooks `:337`). SQS alternative: `core/queue/sqs_client.py:25-27`, consumer started in lifespan `gateway/lifespan.py:250-254`, job runner `core/queue/pipeline_consumer.py:55-118`. Redis is not a job queue.
- Pipeline: semaphore `PIPELINE_MAX_CONCURRENT` default 2 and 30 min timeout `orchestrator/factory_pipeline.py:143-158`; running status `:248`; waves `:408-500`; stage list and critical stages `orchestrator/phase_sequence.py:22-26,90-103`; checkpoint per stage `orchestrator/factory_pipeline.py:688`, stored on the run row `orchestrator/run_state.py:62-76`; control flag `:777-807`; end of run and completion tasks `:811-855`.
- Events: `core/pipeline_state.py:102-130` (pub/sub channel `pipeline:events:{run_id}`, list `pipeline:history:{run_id}`, 24 h expiry, `pipeline_events` table). SSE: `gateway/routers/factory_run_streaming_router.py:36-75,98-211`; nginx stream location `deploy/nginx.conf:117-118`.
- Audit write after the response: `gateway/api.py:160-192`; chain `core/audit/ledger.py:141-190`, `core/audit/chain.py:132-136`.
- S3 and artifact embedding: `orchestrator/artifact_collector.py:66-109`, `core/artifact_store.py:35-93`.
- Velaris proxy: `gateway/velaris_proxy.py:1-18` (rules), `:50` (forbidden body keys), `:99-105` (identity, API key refused), `:108-110` (ledger first). Signing: `core/velaris/client.py:85-114`. Verifier: `velaris/api/auth.py:120-136,148-170` in the Velaris repo; org check `velaris/core/access.py:131-143`.

Not shown / not verified:

- Nothing was run; the order of middleware and the loop are read from code.
- What each stage supervisor does inside a stage (which files, which prompts) was not read. The "write files" step is shown from the project directory and the `output_dir` result (`core/projects.py:16`, `factory_pipeline.py:793`), not from the supervisors.
- Run row creation can fail silently: the insert is in a try block that only logs (`factory_start_router.py:273-274`). The run then has no row until the pipeline saves it at `factory_pipeline.py:248`.
- With SQS, the queue payload carries all fields, but the consumer passes only some of them to `factory.run` (`core/queue/pipeline_consumer.py:100-111`: no personas, mode, intake answers, brand). It also does not call the post build hooks that the in-process path calls. Not run; read only.
- `uvicorn --workers 4` (`Dockerfile:51`) means four processes, each with its own task set and in-memory fallbacks. How runs behave across workers when Redis is absent was not tested.
- Whether the audit middleware sees the `/api` prefix or the stripped path (the inner middleware edits `scope["path"]`) was not tested.
- The Velaris long poll and SSE passthrough variants are not drawn.
