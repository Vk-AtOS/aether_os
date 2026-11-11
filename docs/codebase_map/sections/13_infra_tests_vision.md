# 13_infra_tests_vision — Platform infra, deployment, CI, config, tests, and vision/strategy docs

Scope: Dockerfile, docker-compose*.yml, .dockerignore, deploy/ (systemd, nginx, pgbouncer, fail2ban, logrotate, kubernetes/, scripts/, deploy.sh, setup_vps.sh, setup-bedrock.sh, staging-deploy.sh), helm/aetheros, .github/, scripts/ (24 files + nginx/), pyproject.toml, requirements*.txt, uv.lock, .env.example / .env.staging.example (names only), settings-deep.yml, seed_db.py, conftest.py, benchmarks/, launch/, vendor/, tests/ (33 Python files), and the vision/strategy/audit docs (README, ARCHITECTURE, docs/*, RUNBOOK, SECURITY, COST_MODEL, CHANGELOG, SALE_READINESS, IP_OWNERSHIP, *DUE_DILIGENCE*, PROJECT_STATE_AUDIT, AUDIT_OUTPUT_QUALITY, FIX_LIST, plans2.md, SKILL.md, CONTRIBUTING, SESSION_PROMPTS), the 4 `*_snapshot.md` files, vkatos_deploy/. Git HEAD 052a101 (working tree: `plans2.md` and `agents/implementations.py` modified, snapshot files untracked).

No secret values are reproduced here. Where a credential appears in a file, only file:line and type are given.

---

## 1. Summary

- **What the platform is (per docs):** a proprietary, single-author (IP_OWNERSHIP.md:9-12, Chennai, India) "AI software factory" that turns a plain-English requirement into a deployed full-stack app. Marketing says "39-phase autonomous pipeline" (README.md:3); the code today runs **12 stages wrapping ~50 phase directories** (SALE_READINESS.md:8, DUE_DILIGENCE_AUDIT.md:13; `orchestrator/phase_sequence.py` lists 52 phase ids, `phases/` has 52 `p*` dirs). The phase-count claim has drifted through 10 → 20 → 21 → 26 → 29 → 39 across docs.
- **Deployment reality:** one DigitalOcean VPS (2–4 vCPU) running uvicorn under systemd with 4 workers behind nginx + certbot, local PostgreSQL, Redis, optional PgBouncer and Ollama. Artifacts also exist for Docker Compose (prod + staging on one host), raw Kubernetes manifests, and a Helm chart (Bitnami Postgres/Redis subcharts). Only the VPS path has evidence of real use; K8s/Helm are unexercised templates with several mismatches (§3.8).
- **Deploy flow:** `git pull` → pip install → `alembic upgrade revision_merge_guardian_heads` (+ optional encryption branch) → optional nginx domain sed → dashboard rebuild if changed → `systemctl reload|restart aetheros` → `/health` curl → `scripts/post-deploy.sh` (Guardian file-hash baseline refresh in Redis) → (manual) `scripts/smoke_test.sh`. **The pinned Alembic target is stale**: the migration graph now has 6 heads, and deploy.sh never applies anything beyond `revision_merge_guardian_heads` (§3.10, §8).
- **CI/CD for the platform:** a single GitHub Actions `ci.yml` (pytest + coverage, non-blocking ruff) and an issue-label-triggered `aetheros-generate.yml`. No image build, no deploy, no frontend build/tests, no SAST in CI (despite SECURITY.md claim), no gate on coverage.
- **Tests:** 33 Python test-ish files; **629 `def test_` functions** in 29 pytest modules (SALE_READINESS claims 647 passed incl. parametrised cases). Coverage is concentrated on generators, gates, auth primitives, rate limiting, LLM routing, and stack profiles. **Untested:** all 12 stage supervisors directly, ~25 of 52 phases, 22 of 38 `core/` subpackages (guardian, sandbox, run_app, council, services, webhooks, scheduler, queue, security, notifications, approval, intelligence, knowledge_graph…), almost all 53 gateway routers, SAML/OAuth/MFA/SCIM, alembic migrations, the dashboard (zero frontend tests), CLI, VS Code extension. Tests are mocked end-to-end (plans2.md:187 "100% of 639 tests are mocked").
- **Eval harness:** `scripts/eval_harness.py` (20 golden prompts; build/health/login/CRUD checks against a live instance) and `scripts/benchmark_harness.py` (10 prompts in `benchmarks/prompts/`, stdlib only). `benchmarks/results/` is empty — **no baseline has ever been recorded** (AETHEROS_ACQUISITION_DUE_DILIGENCE.md:48,53).
- **Strategic narrative:** two incompatible valuation stories coexist — V2_EXPANSION_SPEC.md:350-356 ($80K–$1M+) vs STRATEGIC_UPGRADE_PLAN.md:984-991 ($5–8M → $50–100M). The most recent audits (DUE_DILIGENCE_AUDIT 2026-07-20 "5.5/10"; PROJECT_STATE_AUDIT 2026-07-22; AUDIT_2026_08_08) say infra/orchestration is solid but output quality is model-limited (Bedrock Nova, Anthropic payment blocked) and quality gates are mostly non-blocking.
- **Secrets hygiene:** no live API keys in tracked source. But the demo login password and VPS IP remain in tracked scripts/docs/tests (§8.3), `plans2.md:205` (uncommitted edit) contains a plaintext admin password, `.env.example:159` holds a `rzp_live_`-prefixed Razorpay key ID, and untracked LinkedIn PII captures sit at repo root unignored.

---

## 2. Vision, mission, goal, positioning

### 2.1 Stated vision / goal
- README.md:3 — "AetherOS is an AI-powered software factory that transforms a plain-English requirement into a production-ready, compliance-verified, fully deployed application through a **39-phase autonomous pipeline** — the most phases of any known AI application generation system. The nearest competitor runs 8. In under 10 minutes…"
- STRATEGIC_UPGRADE_PLAN.md:2 — subtitle "From AI Code Generator to Compliance-Verified Business Creation Platform"; §6.2 (≈:492-502): end-state "the only software system on earth that can generate a full-stack production application with formal machine-checkable proofs of its security properties. This is a category of one."
- V2_EXPANSION_SPEC.md:3-6 — "Expand AetherOS from a single-stack SaaS generator (FastAPI + React) into a full-spectrum software factory capable of producing any class of business software — microservices, mobile apps, Go/Node services, enterprise ERP, and domain-expert-injected systems."
- pyproject.toml:8 — "AetherOS — Autonomous AI Software Factory"; Helm Chart.yaml:3-5 — "Multi-tenant AI App Factory SaaS".
- PIPELINE_SPEC.md:10-14 — "deterministic sequence of numbered phases (P00–P20)… A central orchestrator (`factory_pipeline.py`) accumulates phase outputs into a shared `accumulated_context`". Declares itself "Authoritative" (:5).
- Launch copy: launch/PRODUCT_HUNT.md tagline "Describe a business app in plain English. Get production code, tests, CI/CD, and a live URL in minutes." Maker comment: goal is eliminating the "plumbing layer" (auth, CRUD, CI, test setup, deploy configs).
- SKILL.md (dated 2026-04-29, stale): original framing "Unified Multi-Agent Software Development System… full 10-phase development pipeline", FastAPI on 8080, SQLite, 61 tests.

### 2.2 Differentiators claimed
- 12 domain knowledge packs with PHI/PCI/PII field tagging, workflow state machines, compliance rules, `BusinessProcessPipeline` (README.md:154-181; packs exist in `core/domain_knowledge/packs/`: ecommerce, edtech, erp, fintech, govtech, healthcare, legaltech, logistics, manufacturing, real_estate, saas, trading — verified).
- Generated artifacts: `compliance_manifest.json` with SHA-256 drift fingerprint + CI `compliance-drift` job, `domain_knowledge.json`, `business_model.json`, `verification_report.json` (Z3), SRE operator (README.md:276-312).
- India regulatory layer (DPDP 2023, RBI, SEBI CSCRF, CERT-In) (README.md:148).
- Competitive matrix vs Lovable / Bolt / Replit / Devin / MetaGPT (README.md:607-626; STRATEGIC_UPGRADE_PLAN.md §6.1).
- Formal verification via Z3 positioned as patent-eligible IP (STRATEGIC_UPGRADE_PLAN.md Phase 4; "File USPTO patent application").

### 2.3 Target users
- README/launch: technical founders, CTOs, engineering managers, investors (launch/DEMO_SCRIPT.md:4), agencies/small teams (COST_MODEL.md "small agencies, teams of 5–20"), regulated verticals (healthcare, fintech, govtech, trading) (STRATEGIC_UPGRADE_PLAN §5.2), enterprise IdP customers (SAML/SCIM), acquirers (SALE_READINESS, DD docs, IP_OWNERSHIP "Clean IP Transfer").
- vkatos_deploy positions the parent brand "VKatOS Private Limited" (settings-deep.yml footer; vkatos pages) selling to Indian enterprises (HR, recruitment, education/study-abroad solutions).

### 2.4 Business model / pricing
- **In-product plans:** trial / pro / enterprise (scripts/create_org.py:91 "trial/pro/enterprise"; launch/TECHNICAL_FAQ.md:113 "trial: 3 runs, pro: 50 runs/month, enterprise: unlimited"). Payments: Razorpay (India) + Stripe (non-India) (`.env.example` sections at :158, :164; Helm secrets). AUDIT_2026_08_08.md:39 H4: pro/enterprise have no seat/quota cap — only rate limits.
- **Illustrative SaaS model:** "$49/month individual plan permitting 50 runs/month… Gross margin ~93–95%" (COST_MODEL.md, "Revenue Model Considerations").
- **Unit economics:** $0.02–0.08 LLM cost/run on Claude Sonnet, $0.22–0.49 all-in per run at 1,000 runs/month; infra $20–40/mo (dev) → $205–405/mo (scale) (COST_MODEL.md). launch/SHOW_HN.md contradicts: "$0.40–$1.20 per run".
- **VKatOS services pricing (vkatos_deploy/pricing):** Starter ₹75,000 setup + ₹25,000/mo; Professional ₹2,00,000 + ₹40,000/mo; Enterprise ₹5,00,000 + ₹75,000/mo (air-gapped, on-site hardware, white-label) — these bundle DCSP/Aether2/Velaris, not AetherOS specifically.
- **Exit strategy:** the repo is explicitly being prepared for sale (SALE_READINESS.md, AETHEROS_ACQUISITION_DUE_DILIGENCE.md, IP_OWNERSHIP.md, FIX_LIST "deal-killers", SESSION_PROMPTS "Sale-worthy").

### 2.5 Roadmap
- **V2 layers (V2_EXPANSION_SPEC.md):** L1 Stack Profile System + intent classification (`core/stack_profiles.py`, `p00_research/stack_selector.py`, Go/Node generators) — "IN PROGRESS" (:34); L2 `p00c_architecture_planner` + full Go/Node + React Native (:196); L3 `core/domain_knowledge/` library (:242); L4 infra expansion + Electron/Tauri desktop + Cobra/Click CLI (:278). All four layers now have code on disk (stack_profiles, p00c, p05b/c/d, domain_knowledge) and tests (test_v2_layers.py, test_v2_integration.py, test_go_*). Phase sequence after layers at :295-327.
- **Strategic Upgrade Plan (docs/STRATEGIC_UPGRADE_PLAN.md):** 10 gaps in 4 phases, all checked `[x]`: Ph1 (3 wk) compliance manifest, transition guards, CI drift gate, `to_dict_full()`, trading/legal packs, spec publication; Ph2 (4 wk) 4 more packs + business model layer; Ph3 (6–8 wk) multimodal intake `p00a_intake` + SRE agent `p21`; Ph4 (3–4 mo) Z3 formal verification `p06b`. IP value milestones $5–8M → $15–25M → $30–50M → $50–100M (:984-991). **Note:** `phases/p00a_intake/` does not exist despite Gap 7 being checked (README.md:49 also lists it).
- **Operational roadmap (FIX_LIST.md / plans2.md / SESSION_PROMPTS.md):** P0 security & secret rotation → P1 frontier model key → P2 honest gates → P3 LLM-first frontend + compile loop + VLM critique (5–7 wk) → P4 cleanup → P5 benchmark + 20-app gallery + fresh DD doc. SESSION_PROMPTS.md drives 5 parallel-agent sessions against the 51-item ledger in plans2.md.

---

## 3. Platform deployment topology

### 3.1 Container image (Dockerfile)
- Stage 1 `node:20-slim` builds `dashboard/` (`npm ci && npm run build`) (Dockerfile:2-11).
- Stage 2 `python:3.11-slim`, apt `postgresql-client curl git`, `pip install -r requirements.lock` (:23-25), copies repo into `/srv/aether_os` so `import aether_os` resolves, copies `dist` into `aether_os/dashboard/dist` (served by FastAPI), `PYTHONPATH=/srv`, `pip install -e`, runs as non-root `aether` (:38-39), `EXPOSE 8000`, HEALTHCHECK `curl /health` (:43-44), CMD `uvicorn aether_os.gateway.api:create_app --factory --workers 4` (:46).
- .dockerignore excludes .env*, .git, caches, node_modules, images, `output/`, `.playwright-mcp/`.

### 3.2 Docker Compose
| File | Services | Ports | Notes |
|---|---|---|---|
| docker-compose.yml | `db` postgres:15-alpine, `redis` redis:7-alpine (256 MB allkeys-lru, `--requirepass` mandatory :27), `api` (build .) | db/redis `expose` only (SEC-004/005, :14-16, :30-32); api `8000:8000` | api env: DB/Redis URLs, `REQUIRE_REDIS=true`, `ENVIRONMENT=production`, JWT RS256/HS256, ZT secret, LLM keys, Bedrock, CORS/FRONTEND_URL required (`:?`), SAML/OAuth, `AETHER_FIELD_KEY`, `SENTRY_DSN`, `AETHER_ADMIN_PASS` required (:87). Volume `aether_os_data:/home/aether/.aether_os`. Postgres password has a dev default (:11). |
| docker-compose.staging.yml | `db_staging`, `redis_staging`, `api_staging` (container names `aetheros_*_staging`) | 5433, 6380, 8001 (host-exposed) | `env_file: .env.staging`; `AETHER_ADMIN_PASS` defaults to `changeme` (:99); volume mounted at `/root/.aether_os` (:106) although the image runs as non-root `aether` (prod fixed this via INFRA-H1, staging did not). |

### 3.3 VPS (bare-metal) topology — the production path
```
Internet ─► nginx :80 (→301) / :443 (certbot TLS, HSTS, CSP, rate limits, fail2ban on access.log)
              ├─ /                      static dashboard (root /opt/aetheros/dashboard/dist, SPA try_files)
              ├─ /api/factory/runs/*/stream  SSE (strip /api, no buffering, 3600s)
              ├─ /api/auth/              auth zone 5r/m burst 3
              ├─ /api/factory/runs/*/run-app 600s timeout
              ├─ /api/*                  api zone 30r/m burst 10, 120s
              ├─ /app-preview/           generated-app preview proxy (JSON 503 fallback)
              ├─ /portal/                client portal (unauthenticated)
              └─ = /metrics              allow 127.0.0.1 only
              ▼
       uvicorn :8000 (systemd aetheros.service, 4 workers, user aetheros)
          ├─ PostgreSQL :5432 (local)  ◄─ optional PgBouncer :6432 (transaction pooling)
          ├─ Redis :6379 (requirepass via scripts/secure_redis.sh)
          ├─ Ollama :11434 (bound 127.0.0.1, ufw deny)
          └─ generated-app processes (run-app, RUN_APP_PORT=8001 in Helm config)
```
- nginx (deploy/nginx.conf): rate zones :29-32, upstream `127.0.0.1:8000 keepalive 64` :36-39, TLS1.2/1.3 :59, security headers incl. CSP with `'unsafe-eval'` :68-74, `limit_conn perip 100` :77, routes :86-221, deny dotfiles/.env/.git :224-227. A second vhost `scripts/nginx/app.vkatos.com.conf` (installed by scripts/vps-setup-subdomains.sh) proxies `app.vkatos.com` → :8000 with SSE at `/api/runs/` and WebSocket `/ws/`, no rate limiting.
- systemd (deploy/aetheros.service): WorkingDirectory `/home/aether_os`, `PYTHONPATH=/home`, venv uvicorn, `Restart=on-failure`, hardening `NoNewPrivileges, PrivateTmp, ProtectSystem=strict, ProtectHome=read-only`, `ReadWritePaths` incl. `/var/backups/aetheros` (:23-27).
- Backups (three overlapping mechanisms — no single source of truth):
  1. `deploy/aetheros-backup.{service,timer}` → `deploy/scripts/backup.sh`: daily 02:00 (+≤10 min jitter), `pg_dump --format=custom -Z9`, retain 30 d, optional `rclone` offsite to remote `backup:`. Timer comments state **RTO 4 h / RPO 24 h** (aetheros-backup.timer:3-5). Paths use `/opt/aetheros`.
  2. `scripts/backup_db.sh` (RUNBOOK's "canonical" one; deploy/crontab.example:8 at 03:00): `pg_dump | gzip`, retain 7 d, local only.
  3. `scripts/db_backup.sh` (installed by `scripts/setup_backup_cron.sh` at 02:00): custom-format dump uploaded to DigitalOcean Spaces via awscli/s3cmd, prunes >7 d remotely; needs `DO_SPACES_*` env.
  Plus in-app Guardian snapshots (`core/guardian/snapshot_manager.py`, rolling window 10, README.md:217) written to `snapshots/guardian/` (65 files on disk, 25 zero-byte `.dump` files tracked in git).
- Log rotation: `deploy/logrotate.d/aetheros` daily, 14 rotations, reload service; crontab.example also deletes `aetheros_*.log` >30 d.
- fail2ban: filter matches nginx 429s and 4xx on `/v2/auth/(login|register|refresh)` (fail2ban/aetheros.conf:8-9); jails ban 600 s after 20/60 s and 3600 s after 10/300 s (aetheros-jail.conf). Note the auth regex targets `/v2/auth/`, while nginx routes `/api/auth/`.
- PgBouncer (deploy/pgbouncer.ini): `127.0.0.1:6432`, scram-sha-256, `pool_mode=transaction`, max_client_conn 200, default_pool 20, reserve 5, admin `pgbouncer_admin`. Userlist (deploy/pgbouncer_userlist.txt:31,33) contains placeholder hashes only.
- Ops helpers: `scripts/harden_env.sh` (chmod 600 /home/aether_os/.env), `scripts/secure_redis.sh` (generate/apply `requirepass`, persist to redis.conf, rewrite REDIS_URL), `scripts/update_nginx_ratelimit.sh` (idempotent zone insertion, `nginx -t` with backup restore), `scripts/update_workers.sh` (set `--workers $(nproc)`), `scripts/vps-setup-subdomains.sh` (certbot for app.vkatos.com).

### 3.4 VPS bootstrap (deploy/setup_vps.sh, Ubuntu 22.04)
apt python3.11/nginx/certbot/pgbouncer/postgresql-client/ufw (:33-39) → Node 20 → Ollama with localhost override (:47-59) → `aetheros` system user → rsync repo to `/opt/aetheros` → venv + `requirements.txt` (unpinned) → dashboard build → `.env` from `.env.example` or an inline template with generated secrets and SQLite default (:79-96) → perms, log dir, logrotate → PgBouncer config → systemd unit → nginx (sed domain) → certbot `--redirect` → ufw (Nginx Full, OpenSSH, deny 11434) → start. Prints admin password to stdout (:165).
- **Path inconsistency:** setup_vps installs to `/opt/aetheros` and nginx root/backup unit/backup.sh use `/opt/aetheros`, but `aetheros.service` (:9-12), post-deploy.sh, harden_env.sh, secure_redis.sh, db_backup.sh, setup-bedrock.sh, update_workers.sh, RUNBOOK §7 all assume `/home/aether_os`. The live VPS uses `/home/aether_os` (per user CLAUDE.md and scripts).
- `deploy/setup-bedrock.sh`: appends `PRIMARY_LLM=bedrock` + AWS creds + Nova Pro/Lite model ids to `/home/aether_os/.env`, `git pull`, `pip install -e .`, runs `seed_db.py` (10 marketplace templates + admin user upsert, seed_db.py:11-310,347-372), restarts, then logs in with the demo account against `localhost:8001` and calls `/api/settings/bedrock/test`.

### 3.5 Staging
`deploy/staging-deploy.sh` creates `.env.staging` (copies prod `.env` if missing — risks prod secrets in staging), rewrites DATABASE_URL to `localhost:5433/aether_os_staging`, REDIS_URL to `:6380` **without password** (:56 — conflicts with compose's mandatory requirepass), builds dashboard, `docker-compose up -d --build`, runs `alembic upgrade revision_merge_guardian_heads` and `add_org_scim_token` inside `api_staging`, curls `:8001/health`. RUNBOOK §11 documents it. Staging co-resides on the prod host.

### 3.6 Raw Kubernetes (deploy/kubernetes/)
namespace `aetheros`; Secret `aetheros-secrets` with `REPLACE_ME_*` placeholders (secret.yaml:20-48); ConfigMap (ENVIRONMENT, REQUIRE_REDIS, CORS, FRONTEND_URL, POSTGRES_DB/USER, WEB_CONCURRENCY=2, LOG_LEVEL); Postgres StatefulSet (1 replica, 20 Gi PVC, pg_isready probes); Redis Deployment (emptyDir — no persistence); API Deployment `aetheros/api:latest`, 2 replicas, RollingUpdate maxUnavailable 0, probes `/health`, 250m/512Mi→1 CPU/1 Gi, mounts emptyDir at `/app/output` (not a path the app uses); HPA 2–10 @70% CPU; Ingress nginx + cert-manager `letsencrypt-prod`, 3600 s timeouts, `yourdomain.com` TODO. README instructs `alembic upgrade head` (README.md:65,90 in k8s dir) — fails with multiple heads.

### 3.7 Helm chart (helm/aetheros)
- Chart v0.1.0 / appVersion 1.0.0; deps Bitnami `postgresql 18.6.7`, `redis 20.6.3` (vendored .tgz + extracted dirs under `charts/`; standard Bitnami charts, not modified — summarized only).
- Templates: deployment (init containers wait for `<release>-postgresql:5432` and `<release>-redis-master:6379`; checksum annotations for config/secret rollouts; non-root uid 1000, drop ALL caps, seccomp RuntimeDefault), service (ClusterIP 80→8000), ingress (disabled by default; paths `/api`, `/ws`, `/`), hpa (2–10, CPU 70 %, mem 80 %), pdb (minAvailable 1), pvc (10 Gi RWO at `/tmp/aether_runs`), serviceaccount (no token automount), configmap, secret (helpers auto-build DATABASE_URL/REDIS_URL from subcharts), NOTES.txt.
- values.yaml config keys: ENVIRONMENT, REQUIRE_REDIS, PRIMARY_LLM=bedrock, BEDROCK_MODEL_HEAVY/LIGHT, AWS_REGION, OLLAMA_MODEL/TIMEOUT, AETHER_API_HOST/PORT, CORS_ORIGINS, FRONTEND_URL, AETHER_ADMIN_EMAIL, PHASE_TIMEOUT_SECONDS=600, SAML_SP_*, DEPLOYMENT_BRAND, SMTP_HOST/PORT/USER, GITHUB_APP_ID, PRICE_CLAUDE_* overrides, METRICS_API_KEY, RUN_APP_PORT=8001, DB_ECHO. Secrets keys: AETHER_SECRET_KEY, AETHER_ONE_ZT_SECRET, AETHER_ADMIN_PASS, ANTHROPIC/GOOGLE/OPENROUTER keys, AWS keys, DATABASE_URL, REDIS_URL, SMTP_PASSWORD, GITHUB_APP_PRIVATE_KEY, GITHUB_WEBHOOK_SECRET, GITLAB_TOKEN, RAZORPAY_*, SLACK_WEBHOOK_URL, SCIM_BEARER_TOKEN, SCIM_ORG_ID (all placeholders).
- Issues: `podAnnotations prometheus.io/path: /api/metrics` (values.yaml) but the app serves `/metrics` only (gateway/routers/metrics_router.py:27) and it requires `METRICS_API_KEY`; RWO PVC shared by an HPA-scaled Deployment with podAntiAffinity → pods on other nodes cannot mount; `METRICS_API_KEY` placed in the ConfigMap (non-secret); no Stripe or JWT RS256 keys in the chart; no migration Job/hook.

### 3.8 How a deploy happens (VPS)
1. Pre-flight per CLAUDE.md (repo): `ast.parse` all files, no file >600 lines, user confirmation, SSH is blocked so commands run via the DigitalOcean web console (user CLAUDE.md, RUNBOOK).
2. `bash deploy/deploy.sh [--domain X]` (deploy/deploy.sh:31-119): `git pull --ff-only` → `pip install -r requirements.txt` (unpinned; Docker uses `requirements.lock`) → `pip install -e .` → `alembic upgrade revision_merge_guardian_heads` (errors swallowed with a warning, :52-53) → `alembic upgrade encrypt_sensitive_columns` if `AETHER_FIELD_KEY` set → nginx sed/reload if `--domain` → dashboard rebuild only if `git diff HEAD@{1} HEAD` touches `dashboard/` → `systemctl reload || restart` with fallback restart + journal dump → `curl /health` (non-fatal) → `scripts/post-deploy.sh`.
3. `scripts/post-deploy.sh`: waits ≤30 s for `/health` `status=ok`; recomputes SHA-256 of 5 critical files (gateway/api.py, gateway/auth.py, core/models.py, core/db.py, alembic/env.py) into Redis keys `guardian:file_hash:<md5(path)>` (:67-87) — connects to Redis **without a password**, so it silently skips when requirepass is set; then tries `POST /auth/login` + `POST /guardian/baseline/refresh` with admin creds (defaults to the demo account, which `core/guardian/password_shield.py:31` blocks).
4. `scripts/smoke_test.sh [base] [email] [pass]` (default base is the VPS IP, :10): `.env` perms warning, `/health`, `/auth/login`, `/api/auth/my-orgs`, `/api/factory/runs`, `/api/system/metrics`, `/api/marketplace/profiles`, `/api/workspaces`, `/api/billing/plans`, `/api/notifications`, `POST /api/memory/search`, SSE token issue, `GET /` → exit 1 on any failure ("do not promote this build"). CLAUDE.md mandates it after each deploy and `git revert` on failure.
5. Rollback (RUNBOOK §7): `git checkout <prev>` + restart; `alembic downgrade -1`.
- `scripts/smoke_test_generated_app.sh`: L1 health, L2 login (preview default creds), L3 CRUD probe over items/users/products/orders/employees, L4 seed-data present — for a generated app.

### 3.9 HA reference (doc only)
RUNBOOK §10: Postgres primary + streaming replica (Patroni/repmgr), PgBouncer per app server, Redis Sentinel/Cluster, 2 nginx active-active + Keepalived, ≥2 API servers, Cloudflare in front, rolling deploy procedure, sized for the 99.9 % SLA in SECURITY.md. None of this is implemented in the repo's automation.

### 3.10 Migrations
56 files / 55 revisions in `alembic/versions`; a naive down_revision parse finds **6 heads**: `add_artifact_embedding_org_fk`, `add_questionnaire_sessions`, `add_scim_token_hash`, `revision_add_missing_tables`, `revision_guardian_timestamptz`, `revision_pgvector_artifact_embedding`. Targets named in docs disagree: deploy.sh / staging → `revision_merge_guardian_heads` (an old merge point); RUNBOOK §0 & CHANGELOG → `add_pipeline_run_checkpoint` "current leaf" (not a leaf anymore: `add_golden_builds_feedback` descends from it); ARCHITECTURE.md:321 says deploy.sh runs `add_pipeline_run_checkpoint`; SALE_READINESS/DD/plans2 → `alembic upgrade heads` (the correct command, done manually). pgvector migration needs `CREATE EXTENSION vector` first.

---

## 4. CI/CD for the platform itself (.github/)

| Workflow | Trigger | What it does | Gaps |
|---|---|---|---|
| `.github/workflows/ci.yml` | push main/dev, PR to main | ubuntu, Python 3.11 + pip cache, Redis 7 service, `pip install -r requirements.lock`, `ruff check --select E,F,W … \|\| true` (:43, **non-blocking**), `pytest tests/ --timeout=300 --cov=. --cov-report=xml`, upload coverage artifact | Env sets `AETHER_ADMIN_PASSWORD` (:24) but code reads `AETHER_ADMIN_PASS` (core/seed.py:20-31, compose INFRA-H2); `REQUIRE_REDIS=false` despite the Redis service; no coverage threshold; no Bandit/Semgrep (SECURITY.md claims "Bandit and Semgrep run in the CI pipeline on every push"); no dashboard lint/build; no Docker build/push; no deploy; `requirements.lock` lacks several runtime deps (§5.4). |
| `.github/workflows/aetheros-generate.yml` | issue labeled `aetheros-generate` | Calls the hosted AetherOS: `POST $AETHEROS_URL/factory/start` with issue body (passed via env to avoid script injection, SEC-C4 :12-15), polls `/factory/runs/{id}` every 10 s, downloads zip, commits to branch `aetheros/<run>`, `gh pr create` | Infinite loop if run ends `failed` (only breaks on `completed`, :28-32); no job timeout; `gh` needs `GH_TOKEN` and `permissions: contents/pull-requests: write` (not declared); payload key `requirement` vs `raw_input` used elsewhere (benchmark_harness). This is a product feature (GitHub-issue-to-PR), not platform CI. |
- `.github/CODEOWNERS`: `* @AetherOS`.
- No CD: deploys are manual console runs of deploy.sh. No release/tag workflow (CHANGELOG links to `github.com/Vk-AtOS/aether_os` tags).

---

## 5. Configuration surface (variable NAMES only)

Source: `.env.example` (line numbers), `.env.staging.example`, compose, Helm, scripts.

- **LLM providers & routing:** PRIMARY_LLM (:8), ANTHROPIC_API_KEY (:9), OPENROUTER_API_KEY (:14), AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION (:19-21), AWS_DEFAULT_REGION (compose), AWS_BEARER_TOKEN_BEDROCK (audits), BEDROCK_ENABLED (:49), BEDROCK_MODEL_HEAVY, BEDROCK_MODEL_LIGHT (:26-27), OLLAMA_MODEL, OLLAMA_TIMEOUT (:30-31), OLLAMA_BASE_URL, GOOGLE_API_KEY (:35), LLM_PROVIDER, RETRIEVER, OFFLINE_MODE (air-gapped block :197-209), PRICE_CLAUDE_SONNET_4_6_INPUT/OUTPUT, PRICE_CLAUDE_HAIKU_4_5_INPUT/OUTPUT, PRICE_CLAUDE_OPUS_4_6_INPUT/OUTPUT, PRICE_DEFAULT_INPUT/OUTPUT (:224-231), LangSmith vars (not in example).
- **Database / cache / queue:** DATABASE_URL (:125), DB_ECHO (:156), POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_USER (compose/k8s), REDIS_URL (:40), REDIS_PASSWORD (:44), REQUIRE_REDIS (compose), SQS_QUEUE_URL, PIPELINE_MAX_CONCURRENT (:55-56), BACKUP_DIR, BACKUP_RETAIN, RETAIN_DAYS, DO_SPACES_KEY/SECRET/BUCKET/ENDPOINT (backup scripts).
- **Auth / identity / crypto:** AETHER_JWT_PRIVATE_KEY_B64, AETHER_JWT_PUBLIC_KEY_B64 (:66-67), AETHER_SECRET_KEY (:72), AETHER_FIELD_KEY (:76), AETHER_ONE_ZT_SECRET (:80), AETHER_ADMIN_EMAIL, AETHER_ADMIN_PASS (:87-88) — staging/air-gapped docs use AETHER_ADMIN_USER / AETHER_ADMIN_PASSWORD instead (naming drift), GITHUB_CLIENT_ID/SECRET, GOOGLE_CLIENT_ID/SECRET (:93-98), SAML_IDP_ENTITY_ID, SAML_IDP_SSO_URL, SAML_IDP_CERT (:104-107), SAML_SP_ENTITY_ID, SAML_SP_ACS_URL (compose), SCIM_BEARER_TOKEN, SCIM_ORG_ID (:218-219), PREVIEW_JWT_SECRET, PUBLIC_HOST (plans2 E-8), CORS_ORIGINS (:121), FRONTEND_URL.
- **Billing:** RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET (:159-162), STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_PRO, STRIPE_PRICE_ENTERPRISE (:166-172).
- **Observability / notifications:** SENTRY_DSN (:112), METRICS_API_KEY (:239; ephemeral if unset — AUDIT_2026_08_08 M10), SLACK_WEBHOOK_URL (:141), SMTP_HOST/PORT/USER/PASSWORD (:142-145), WAHA_URL (WhatsApp, :180), LOG_LEVEL, WEB_CONCURRENCY (k8s).
- **Integrations / SCM:** GITHUB_TOKEN (:117), GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY_PATH (GITHUB_APP_PRIVATE_KEY in Helm), GITHUB_WEBHOOK_SECRET (:148-150), GITLAB_TOKEN (:153), DCSP_URL, DCSP_API_KEY (:194-195), AETHEROS_URL / AETHEROS_TOKEN (GH Action secrets).
- **Runtime / pipeline / feature flags:** ENVIRONMENT, AETHER_CONFIG_PATH, AETHER_REPO_ROOT (:131-132), AETHER_API_HOST/PORT (:135-136), PHASE_TIMEOUT_SECONDS (:176), RUN_APP_PORT (:184), DEPLOYMENT_BRAND (white-label, :189), COUNCIL_ENABLED, COUNCIL_STRICT_MODE (README.md:211; strict mode off in .env per audits), ARTIFACT_DIR (staging :85), OFFLINE_MODE.
- **Other config files:** `pyproject.toml` (setuptools, maps package `aether_os` → repo root `package-dir = {"aether_os" = "."}`, pytest `asyncio_mode=strict`, `pythonpath=[".."]`, ignores `test_bedrock_integration.py`); `conftest.py` (registers repo root as `aether_os` namespace for worktrees; autouse fixture resets `orchestrator.run_state._PIPELINE_SEMAPHORE`); `uv.lock` (stub, only the editable project); `VERSION` 1.0.0; `alembic.ini`.
- `settings-deep.yml` is **not config**: it is a Playwright ARIA snapshot of the dashboard Settings page (nav: Dashboard, New Project, Projects, Search, Deployments, Marketplace, Intelligence, System Health, Pricing, Settings, Compliance, Tools; Admin: Users, Audit Logs, Billing, Client Portal; active LLM `openrouter (minimax/minimax-m2.5:free)`; footer "© 2026 VKatOS Private Limited — AetherOS Factory v1.0").
- `vendor/VENDOR_MANIFEST.json`: record of an environment provisioning (2026-04-19) — pip packages (crewai, langchain*, langgraph, aider-chat, semgrep, mem0ai, UnleashClient, growthbook, posthog, sentry-sdk…), docker services (waha, posthog, sentry, unleash, growthbook, prometheus, grafana, alertmanager), npm tools (storybook, openapi-generator-cli), playwright chromium. Nothing vendored in-tree.

### 5.4 Dependencies
- `requirements.txt` (unpinned, `>=`): FastAPI/uvicorn/pydantic, SQLAlchemy async + aiosqlite + asyncpg + alembic, passlib/bcrypt, PyJWT, cryptography, slowapi, python3-saml, pyotp, anthropic, boto3, google-genai, httpx, typer/rich, networkx, whatthepatch, mcp, sqlite-vec, razorpay, stripe, websockets, watchdog, cookiecutter, bandit, hypothesis, z3-solver, locust, playwright, axe-playwright-python, pdoc, diagrams, fpdf2, mem0ai, chromadb, UnleashClient, growthbook, posthog, sentry-sdk, prometheus-client, prometheus-fastapi-instrumentator==6.1.0, structlog, langsmith, redis, psutil, ldap3, plus test deps (pytest*, ruff).
- `requirements.lock` (pinned, used by Dockerfile and CI) is **missing** `stripe`, `mcp`, `whatthepatch`, `prometheus-fastapi-instrumentator`, `ldap3`, `pytest-json-report` → Docker image / CI may lack imports used at runtime (gateway/api.py:148 references `excluded_handlers` from the instrumentator). VPS installs from the unpinned file, so prod and container differ.
- README tech stack says "python-jose JWT"; code/lock use PyJWT (IP_OWNERSHIP license table also lists python-jose). Semgrep is listed as used but not in requirements (vendor manifest only).

---

## 6. Test suite inventory and coverage map

### 6.1 Inventory (tests/, 629 test functions)
| File | Lines / tests | Covers (imports) |
|---|---|---|
| test_core.py | 364 / 29 | core.errors, config.loader, db, audit.logger/ledger, memory.store/fingerprinter, policy.engine, orchestrator.state_machine |
| test_factory.py | 376 / 19 | orchestrator.bus/messages/factory_pipeline, core.projects, core.billing UsageTracker (token pricing) |
| test_factory_extended.py | 328 / 11 | factory_pipeline smoke/start phase, 26-phase state machine transitions, client_portal routes |
| test_pipeline.py | 284 / 13 | orchestrator.context, legacy orchestrator.pipeline, pipeline_helpers, routing.router |
| test_integration_pipeline.py | 430 / 17 | PHASE_SEQUENCE/supervisor mapping, run_phase, PHASE_TIMEOUT env, p07 gate thresholds, bus |
| test_integration_pipeline_extended.py | 307 / 4 | full pipeline run with mocks ("all 20 phases"), GateOutcome |
| test_e2e_pipeline_smoke.py | 303 / 4 | mocked 12-stage run, parallel_runner `_safe_copy` |
| test_phases.py | 312 / 16 | gate pass/fail for p00–p10 |
| test_phases_later.py | 422 / 20 | p05f vite/nginx writer, p06 security report, p07a fallback tests, p08 ci.yml, p09 |
| test_l5_cloud_primitives.py | 351 / 40 | cloud_primitives storage/queue/gateway (MinIO, NATS, Kong), cell_architecture, chaos_engineering, capacity_planner |
| test_l6_l8_phases.py | 532 / 45 | p05e serverless (Knative), p16 IAM (OPA/Keycloak), p17–p20 |
| test_go_generator.py | 449 / 63 | p04 Go/Gin model/handler/router generation |
| test_go_grpc_generator.py | 358 / 55 | proto/gRPC generation |
| test_v2_layers.py | 599 / 71 | stack_profiles, Go/Node generators, domain_knowledge loader |
| test_v2_integration.py | 425 / 46 | profile routing, domain packs, compliance.manifest_writer, business model |
| test_llm.py | 296 / 9 | core.llm.client (Anthropic primary, Gemini, fallback, JSON parsing, cost stats) |
| test_model_router.py | 322 / 27 | model_router fallback chain, error classification, provider config, llm.ahm, langsmith_tracer |
| test_memory.py | 178 / 13 | core.memory.store |
| test_project_fingerprinter.py | 181 / 18 | core.memory.fingerprinter |
| test_quality_metrics.py | 315 / 24 | core.quality.metrics `score_project` |
| test_gateway.py | 245 / 13 | gateway.api TestClient: /health, login, protected routes, pipeline start auth, CORS, JWT, ZT secret |
| test_billing_webhook.py | 250 / 11 | Razorpay webhook signature, cancel/downgrade, invoices auth |
| test_multi_tenancy.py | 172 / 1 | cross-org isolation workflow via API |
| test_rate_limiting.py | 62 / 4 | core.rate_limiter limits |
| unit/test_db.py | 184 / 11 | core.db URL normalisation, SQLite fallback, session factory |
| unit/test_rate_limiter.py | 238 / 21 | IP bucketing, localhost exemption, Redis strict-mode deny |
| unit/test_security.py | 246 / 23 | gateway.auth bcrypt, API keys, JWT (expiry, jti, tamper, refresh) — real crypto |
| test_bedrock_integration.py | 121 / 1 | live Bedrock call (excluded by pyproject addopts) |
| load/locustfile.py, load/seed_load_users.py | — | Locust BrowseUser/etc. against VPS (/auth/login, /factory/runs, /system/costs, /compliance/org-report, /audit/logs, /account/storage, /marketplace/profiles); seeds 60–550 load users |
| playwright_full_audit.py (+ playwright_audit_report.md "37/37 PASS", 2026-05-30) | — | live-VPS UI audit of 20 tabs |
| monitor_live_build.py | — | starts a live run on VPS and tails logs |
- `.pytest_cache/v/cache/lastfailed` lists 3 entries, incl. `test_phase_sequence_is_20_phases` and a now-deleted `test_l5_l8_phases.py` — cache is stale. Test-count claims across docs: 61 (SKILL.md), 153 (old main.py banner), 462 (STRATEGIC_UPGRADE_PLAN:83), 535+ (README.md:653), 584 (DUE_DILIGENCE_AUDIT), 600+/643 (vkatos), 639 (plans2), 647 (SALE_READINESS), 650 (ACQUISITION DD).
- Internal inconsistency: tests assert 12 stages (e2e), 20 phases (extended), 21 phases (integration), 26 phases (factory_extended).

### 6.2 Coverage map (module → tested?)
- `core/` subpackages tested (16): audit, billing, capacity_planner, cell_architecture, chaos_engineering, cloud_primitives, compliance (manifest_writer only), config, domain_knowledge, identity, llm, memory, policy, quality, telemetry, + stack_profiles/model_router/rate_limiter/db modules.
- `core/` subpackages **untested** (22): approval, bootstrap, connectors, council, decisions, domain_packs, guardian, intelligence, knowledge_graph, learning, notifications, plugins, questionnaire, queue, run_app, sandbox, scheduler, security, services, snapshot, validators, webhooks.
- Phases imported by tests (27): p00_research, p00c, p01, p02, p03, p04_backend, p04a, p04b, p05_frontend, p05e, p06, p07, p07a, p08_cicd, p09_documentation, p11_deployment, p11a, p16–p20. **Untested (25):** p00b, p01b, p02b_domain_ir, p02c_permission_modeling, p04_uiux_design, p04c, p05b_mobile, p05c_desktop, p05d_cli, p06b_formal_verification, p07b_performance_testing, p07b_self_healing, p07c, p07d, p08_cicd_deployment, p09_observability, p10, p11b–p11e, p12a, p12b, p13, p14, p15, p21_sre_agent, patterns.
- `stages/s01–s12` supervisors: never imported by tests (mocked in e2e smoke).
- `gateway/`: 53 router files; tests touch auth_router + a handful of endpoints via TestClient. No tests for auth_saml/auth_oauth/auth_mfa, SCIM, admin, guardian, metrics, run-app, FDE file/envvar endpoints, marketplace, webhooks, workspaces, compliance, MCP router.
- `agents/`, `cli/`, `integrations/`, `alembic/`, `dashboard/` (no `*.test.*`/`*.spec.*`, package.json has only `lint`), `vscode-extension/`, deploy scripts, Helm: **no tests**.
- Nature: all mocked (no real Postgres, npm/tsc, or LLM) — plans2.md:187-192 D-1..D-4.

### 6.3 Eval / golden harness
- `scripts/eval_golden_prompts.py`: 20 `(domain, prompt)` pairs (crm, fintech, healthcare, restaurant…).
- `scripts/eval_harness.py` (464 lines): async httpx; logs into platform (defaults to the demo account, :280-281), `POST /factory/start`, polls `/api/factory/runs/{id}` (900 s timeout), checks generated app `/run-app/{id}/health`, login with preview default creds (:17-18, :172), CRUD on an entity; concurrency 3; prints Build/Health/Login/CRUD table; JSON report; exit 1 on failure.
- `scripts/benchmark_harness.py` (185 lines, stdlib only): 10 prompts from `benchmarks/prompts/01_crm_leadsync.md … 10_realestate_proptrack.md`, `raw_input` + `autonomous_mode`, 15 s poll, 20 min timeout, writes JSON + Markdown to `benchmarks/results/` (empty).
- Golden example corpus builders → `core/knowledge_graph/golden_examples/`: `seed_golden_examples.py` + `seed_golden_helpers.py` + `seed_golden_extra.py` (hand-curated domain IR examples + bug-fix examples, split to respect 600-line rule), `spider_to_golden_examples.py` (HuggingFace `b-mc2/sql-create-context` CREATE TABLEs → SQLAlchemy entities), `github_corpus_builder.py` (GitHub API top FastAPI repos → entity patterns), `so_corpus_builder.py` (Stack Overflow dump streaming → bug→fix pairs).
- Data maintenance: `backfill_billing.py` (synthesise LLMCallRecord from per-phase median tokens), `backfill_quality.py` (score completed runs + GlobalPattern), `embed_existing.py` (embed artifacts of completed runs), `create_org.py` (create org + owner with plan; prints password).

---

## 7. Plane mapping

| Plane | Artifacts in this scope |
|---|---|
| **Deployment** | Dockerfile, compose (prod/staging), deploy.sh, setup_vps.sh, setup-bedrock.sh, staging-deploy.sh, systemd unit, nginx.conf + app.vkatos.com vhost, k8s manifests, Helm chart, post-deploy.sh, update_workers.sh, vps-setup-subdomains.sh |
| **SRE / reliability** | health checks (Docker/compose/k8s/Helm probes), systemd Restart, HPA/PDB, backups ×3 + Guardian snapshots, RTO 4h/RPO 24h, logrotate, RUNBOOK (DB/Redis/LLM outage, stuck run, OOM, TLS, rollback, restore, SQLite→PG, HA), SECURITY.md SLA 99.9 % / P1–P3 response, smoke_test.sh, Locust load tests (p95 240 ms @50 users claimed in CHANGELOG), COST_MODEL capacity |
| **Security** | nginx TLS/headers/CSP/rate limits/sensitive-path blocks, fail2ban, ufw, Ollama localhost bind, Redis requirepass, non-root container/systemd hardening, harden_env.sh, secure_redis.sh, k8s/Helm securityContext, SECURITY.md disclosure policy, JWT RS256 key vars, field encryption key, Guardian file-integrity baseline, unit/test_security.py, test_gateway JWT/ZT tests |
| **Compliance** | (platform) audit-log hash chaining & CSV export (CHANGELOG), DPDP-ready claims (vkatos), IP_OWNERSHIP license review; (generated) compliance manifest/drift gate tests in test_v2_integration; STRATEGIC_UPGRADE_PLAN compliance roadmap; RPO/RTO statement |
| **STLC / testing** | tests/ (§6), CI pytest+coverage, eval_harness, benchmark_harness, golden corpora, playwright audit, smoke tests, Locust |
| **SDLC** | CONTRIBUTING (conventional commits, squash-merge, 1 review), CLAUDE.md rules (600-line cap, one commit per fix, root-cause messages), CODEOWNERS, SESSION_PROMPTS (agentic multi-session dev process), plans2/FIX_LIST ledgers, CHANGELOG/semver, VERSION |
| **Admin control** | AETHER_ADMIN_EMAIL/PASS seed (seed_db.py, core/seed.py), create_org.py, smoke checks of admin endpoints, settings-deep.yml shows admin nav (Users, Audit Logs, Billing, Client Portal) |
| **API management** | nginx path routing (/api prefix stripped), per-zone rate limits, `/metrics` localhost-only + METRICS_API_KEY, Helm ingress paths, API_REFERENCE.md (out of scope), aetheros-generate.yml as external API client |
| **Billing / business** | Razorpay/Stripe env, plan tiers, COST_MODEL, backfill_billing.py, vkatos pricing |
| **Observability** | SENTRY_DSN, Prometheus annotations, structlog, LangSmith, `/metrics` |
| **LLM ops** | PRIMARY_LLM/Bedrock/Ollama/OpenRouter/Gemini config, setup-bedrock.sh, AIR_GAPPED_SETUP (OFFLINE_MODE + Ollama + DuckDuckGo retriever), price overrides |

---

## 8. Reality check

### 8.1 Doc claims vs code
| Claim | Source | Reality |
|---|---|---|
| "39-phase pipeline" | README.md:3,40; STRATEGIC_UPGRADE_PLAN:25; vkatos index | 12 stages; 52 phase ids in phase_sequence; most "phases" are libraries called by stage supervisors (`INACTIVE_PHASE_DIRS`, phase_sequence.py:30-46). ARCHITECTURE says 21, PIPELINE_SPEC P00–P20 (39 rows), launch docs 20, CHANGELOG 0.1.0 21, V2 spec 29. |
| `p00a_intake` multimodal intake (Figma/diagram/voice) done | README.md:49; STRATEGIC_UPGRADE_PLAN Gap 7 `[x]` | directory does not exist |
| SAML/SCIM/OAuth/MFA implemented | README.md:318-325; ARCHITECTURE:222-230 | plans2.md:427-431 depth map says "Enterprise Features — L0… no SAML/SCIM routes", but `gateway/auth_saml.py`, `auth_oauth.py`, `auth_mfa.py` exist and playwright report shows SSO/SCIM settings. Conflict needs code verification (other sections). MFA not mandatory (AUDIT_2026_08_08 H5). |
| "Bandit and Semgrep run in the CI pipeline on every push" | SECURITY.md (Security Architecture) ; CHANGELOG 0.1.0 | ci.yml has neither |
| "No hardcoded credentials" | SECURITY.md; ACQUISITION DD "VPS IP, credentials, and demo passwords removed from all documentation" | still present in README, STRATEGIC_UPGRADE_PLAN, launch/, scripts, tests (§8.3) |
| "535+ tests. 0 failures. CI runs on every push to main" | README.md:653 | 629 functions; CI also runs on dev; DUE_DILIGENCE_AUDIT found 3 failing router tests (later fixed per SALE_READINESS) |
| Quality gates block | launch/SHOW_HN ("orchestrator never proceeds if a gate fails"), PRODUCT_HUNT | COUNCIL_STRICT_MODE off; stages s05–s12 non-blocking; s06 always passed=True (AUDIT_2026_08_08 C2, M5) |
| "Output in under 10 minutes" | README.md:3 | vkatos product page: 25–45 min; AIR_GAPPED 45–90 min CPU; COST_MODEL 3–10 min |
| deploy.sh migrates to current leaf | ARCHITECTURE.md:321; RUNBOOK §0 | deploy.sh pins `revision_merge_guardian_heads`; graph has 6 heads |
| "Python files 9,190 / 756,428 lines" | ACQUISITION DD | ~816 first-party .py (excl. .venv); SALE_READINESS 755 / 209.7K; DUE_DILIGENCE 748 / 143.8K (likely the DD counted .venv) |
| SALE_READINESS evidence paths `phases/p09_devops/`, `phases/p08_compliance/`, `phases/p06_testing/` | SALE_READINESS.md capability table | none exist |
| "Router files 14" | SALE_READINESS | 53 in gateway/routers |
| Tech stack "python-jose" | README.md:578; IP_OWNERSHIP | PyJWT |
| CONTRIBUTING: pre-commit secret hooks, `black`, `npm test`, `npm run type-check`, `.eslintrc`, phases `supervisor.py`, tests in `tests/phases/` | CONTRIBUTING.md:74-109,159-169 | no `.pre-commit-config.yaml`, no black in deps, package.json has only `lint`, phases use `supervisor_agent.py`, no `tests/phases/` |
| HA / 99.9 % SLA | SECURITY.md SLA; RUNBOOK §10 | single VPS; "100% Uptime SLA" on vkatos index |
| Valuation | V2 spec $80K–$1M+ vs Strategic plan $5–100M | mutually inconsistent; both pre-date the audits that call output "uncompetitive" (DUE_DILIGENCE_AUDIT §10) |

### 8.2 Infra defects found while reading
1. `deploy/nginx.conf:18-32` puts `worker_processes`, `events{}`, and `limit_req_zone` outside `http{}` and wraps servers in its own `http{}` — invalid if dropped into `sites-available` (which nginx includes inside `http`) as setup_vps.sh:135 does; it only works as a full `nginx.conf`. `update_nginx_ratelimit.sh` inserts different zone names (`auth_limit`, `api_limit` at 60 r/m) than nginx.conf (`auth`, `api` at 30 r/m).
2. Path split `/opt/aetheros` vs `/home/aether_os` (§3.4).
3. Staging REDIS_URL patched without password (staging-deploy.sh:56) vs mandatory requirepass; staging volume `/root/.aether_os` vs non-root user.
4. post-deploy.sh Redis without auth; login fallback uses a blocked password.
5. Helm `/api/metrics` scrape path, RWO PVC + HPA, METRICS_API_KEY in ConfigMap.
6. k8s README `alembic upgrade head` fails (multiple heads); API emptyDir mount `/app/output` unused.
7. `requirements.lock` missing 6 deps; VPS uses unpinned requirements.
8. CI admin-password env name mismatch; lint non-blocking.
9. aetheros-generate.yml can loop forever.
10. fail2ban auth regex `/v2/auth/` vs nginx `/api/auth/`.
11. Three backup scripts with different formats, schedules, retention, destinations; RUNBOOK names `scripts/backup_db.sh` canonical while systemd timer runs `deploy/scripts/backup.sh`.
12. setup_vps.sh echoes admin password to the terminal (:165); create_org.py prints password (:87).

### 8.3 Hardcoded secrets / credentials (file:line + type only)
- **Demo account password (shared demo login)**: deploy/setup-bedrock.sh:80; scripts/post-deploy.sh:15 (default); scripts/smoke_test.sh:12 (default); scripts/eval_harness.py:281 (argparse default); tests/monitor_live_build.py:17; tests/playwright_full_audit.py:19; tests/load/locustfile.py (header usage :5-15); launch/SHOW_HN.md:60; launch/TWITTER_THREAD.md:106. (Same string appears in core/guardian/password_shield.py:31 and core/seed.py:39 as a *blocked* password — not a leak.)
- **Production VPS IP** (infra identifier): README.md:484; docs/STRATEGIC_UPGRADE_PLAN.md:82; deploy/setup-bedrock.sh:95,97; scripts/smoke_test.sh:10; tests/load/locustfile.py:5,8,9,14,15; tests/playwright_full_audit.py:2,17; tests/monitor_live_build.py:15; launch/SHOW_HN.md:60; launch/TWITTER_THREAD.md:106; plans2.md:15.
- **Plaintext admin password for VPS** — plans2.md:205 (E-8 row) — in the *uncommitted* working-tree edit (not in HEAD); must not be committed.
- **AWS access key ID fragment** — plans2.md:13 (S2 row, partial `AKIA…` id, committed).
- **Razorpay key ID with `rzp_live_` prefix** — .env.example:159 (key id, not secret; still a live-account identifier in a template).
- **Default DB password in a script** — scripts/backfill_quality.py:10 (`DATABASE_URL` setdefault with embedded password).
- **Dev default Postgres password** — docker-compose.yml:11,48; docker-compose.staging.yml:21,60; deploy/staging-deploy.sh:47,50 (fallback when POSTGRES_PASSWORD unset).
- **Default admin password `changeme`** — docker-compose.staging.yml:99.
- **Generated-app preview creds/secret** — scripts/smoke_test_generated_app.sh:9, scripts/eval_harness.py:18,172 (preview admin password); tests/load/seed_load_users.py:72 (load-test admin password). Audits also cite core/run_app/process_manager_helpers.py:182,307 (preview password, preview JWT secret) — outside this scope.
- **CI test secrets** — .github/workflows/ci.yml:21-24 (test-only JWT/ZT secrets and admin password; acceptable for CI).
- Placeholders only (OK): deploy/kubernetes/secret.yaml, helm values.yaml, deploy/pgbouncer_userlist.txt:31,33, setup-bedrock.sh:18-19.
- Out of repo but relevant: the user's global `~/.claude/CLAUDE.md` stores the VPS root password in plaintext; `.env` (untracked, gitignored) holds live AWS keys/JWT/ZT/SCIM secrets per audits (rotation pending: plans2 S2/E-4/E-5).
- History: JWT file purged with git-filter-repo per SALE_READINESS (S1), force-push still pending (plans2 E-6).

### 8.4 Open items (plans2.md / audits) — still open as of latest docs
- Human/operator: Anthropic payment / frontier key (E-1, P3), `alembic upgrade heads` on VPS (E-2/P1), Bedrock token (E-3), AWS + all secret rotation (S2, E-4, E-5), force-push rewritten history (E-6), VPS deploy + .env update (E-7, E-8), pgvector extension (E-9), benchmark baseline (Q12), 20-app gallery.
- Engineering: A-1 domain lookup tables, A-2 generic seed data, A-3 palette-lookup design system, A-5 1,259 function-scoped imports (worsened), B-2 frontend scoring (no eslint/axe), B-3 pgvector inactive, B-5 thin CI/CD generation, C-1/H4 billing enforcement for pro/enterprise, C-2 council non-blocking, C-3 stages s05–s12 non-blocking, C-4/H5 MFA not mandatory, D-1..D-4 mocked tests / no real E2E / no CI gate / generated code never compiled in CI; AUDIT_2026_08_08 C1 (snapshot PII), C3 (generated preview CORS `*`+credentials), H1–H3 swallowed exceptions, H6, H7 router >400 lines, H9 227 raw DB calls in routers, M4 files at 600 lines, M6 `snapshots/` not ignored, M10 ephemeral METRICS_API_KEY; PROJECT_STATE_AUDIT W1 (VLM critique never sends image), W2 (`@` alias missing in generated vite/tsconfig), W4 ordering, W5 sequential page gen vs watchdog, W6; SALE_READINESS: generated apps' password reset never emails, preview JWT secret hardcoded.
- Doc items: D4/D5 in plans2 (AUDIT_OUTPUT_QUALITY stale 30 s claim) still TODO; plans2 marks Q3/Q4 TODO although implemented (AUDIT_2026_08_08 M1/M2).

### 8.5 Stale / misleading docs
- SKILL.md (2026-04-29: 10 phases, SQLite, port 8080, 61 tests, `COMPLETION_REPORT.md` that no longer exists) — stale.
- ARCHITECTURE.md (21 phases, Redis bus design, deploy steps) — partially stale; superseded by 12-stage model.
- README.md and STRATEGIC_UPGRADE_PLAN.md — inflated counts, VPS IP, p00a.
- launch/* (20-phase pipeline, Razorpay-only billing in TECHNICAL_FAQ, live demo creds) — stale marketing.
- RUNBOOK §0 migration leaf and §8 backup canonical script — stale.
- AETHEROS_ACQUISITION_DUE_DILIGENCE.md — wrong file/line counts.
- CONTRIBUTING.md — process tooling that does not exist.
- AIR_GAPPED_SETUP.md:15 uses `aether_os.gateway.api:app` (module attr) whereas all deploy paths use `create_app --factory`; "All 20 phases complete successfully".
- COST_MODEL assumes 21 calls/run and `deepseek-prover-v2:free`; current runtime is Bedrock Nova (SALE_READINESS "Active LLM runtime").

### 8.6 Other repo-root artifacts
- `barath_snapshot.md`, `senthil_snapshot.md`, `sreshta_snapshot.md`, `sudharsan_snapshot.md` (105–132 KB each, untracked): Playwright ARIA accessibility-tree captures of **LinkedIn pages** (named individuals' profiles; hundreds of `linkedin` references each) — personal data unrelated to the product; AUDIT_2026_08_08.md:10-11 C1 flags them; `.gitignore:86` only ignores `.aether_snapshots/`. Should be deleted.
- `spmc-*.png` (6 screenshots, ignored by .dockerignore) — a generated shop app's admin/shop pages.
- `vkatos_deploy/` (32 tracked files; plans2 H3 says it was "moved or deleted" in 7321902 but it is present and tracked): static marketing site for **VKatOS** (Chennai) — pages: home, about, blog (offline-ai, recruitment-automation, stall-detection), book-demo, careers, case-studies, contact, dashboard, industries, login (calls `https://app.vkatos.com/api/auth/password-reset-request`), partners, portal, pricing, privacy, terms, products (AetherOS, Aether2, DCSP, Velaris), solutions (custom, education, hr, recruitment), 404, robots, sitemap, `nav.js`. Product claims: AetherOS "39-phase autonomous pipeline… zero boilerplate… real AI-written code", "<15m idea to deployment", "600+ tests passing", "100% Uptime SLA", "SOC 2, HIPAA, GDPR" compliance engine; product page "643/643 tests", "Generation time 25–45 minutes", "Python, TypeScript, Go". Aether2 = "multi-step AI pipelines that survive failure… MoE architecture, Ollama native"; DCSP = "pipeline monitor that predicts failures before they happen, 469 tests, offline-first" (integrated via DCSP_URL/DCSP_API_KEY); Velaris = enterprise real-time pipeline dashboard (private beta). Pricing ₹ tiers in §2.4.

---

## 9. Open questions

1. Which install path is canonical on the VPS — `/home/aether_os` (systemd, scripts) or `/opt/aetheros` (setup_vps, nginx root, backup unit)? Is the nginx running in prod the repo's nginx.conf or a hand-edited site file?
2. Which backup actually runs in prod (timer → `deploy/scripts/backup.sh`, cron → `backup_db.sh`, or `db_backup.sh` → Spaces)? Has a restore ever been tested against the 4 h RTO?
3. What Alembic revision is the VPS at, and who reconciles the 6 heads (merge migration vs `upgrade heads`)? deploy.sh should be changed to `heads` or a merge revision.
4. Has the Docker image ever been built/run successfully given `requirements.lock` lacks stripe/mcp/whatthepatch/prometheus-fastapi-instrumentator/ldap3?
5. Are K8s manifests / Helm chart ever deployed anywhere, or are they sale collateral? (No CI builds `aetheros/api`.)
6. Do SAML/SCIM endpoints work (README) or are they L0 (plans2 depth map)? Needs gateway section cross-check.
7. Does CI currently pass with `AETHER_ADMIN_PASSWORD` instead of `AETHER_ADMIN_PASS`, or do tests mock the seed?
8. Has the uncommitted plans2.md change (plaintext admin password at :205) been noticed — will it be committed? Has that password been used on the VPS (then it must be rotated)?
9. Has `benchmark_harness.py`/`eval_harness.py` ever produced a result? `benchmarks/results/` is empty.
10. Is the demo account still active on the VPS given `password_shield` blocks that password (AUDIT_2026_08_08 C4 says demo login is broken)?
11. Which valuation/positioning narrative (V2 spec vs Strategic plan vs DUE_DILIGENCE 5.5/10) is the owner's current one, and should the "39-phase" marketing be retired in favour of "12 stages"?
