# AetherOS Technical FAQ

---

## Pipeline Architecture

### How does the 20-phase pipeline work?

Each pipeline phase is an independent Python module that:

1. Reads its input from the MessageBus (Redis RPUSH/BLPOP)
2. Executes its logic (LLM calls, static analysis, test execution, etc.)
3. Evaluates a quality gate (returns a `GateResult` with a confidence score)
4. Publishes its output back to the MessageBus if the gate passes

The orchestrator (`orchestrator/factory_pipeline.py`) drives phase sequencing but never calls phase logic directly — it only reads and writes to the MessageBus. This makes phases independently testable and replaceable.

### What is a quality gate?

A quality gate (`gate.py` in each phase) evaluates the phase output against a set of criteria and returns a confidence score between 0.0 and 1.0. If the score is below the threshold (default: 0.7), the pipeline pauses. For testing failures, p07b Self-Healing is triggered first. For other failures, the pipeline surfaces the failure to the operator.

### How does self-healing (p07b) work?

p07b reads the failing test output, identifies the implicated files, generates a targeted patch using the LLM, applies the patch, and re-runs the failing tests. It repeats this loop up to a configurable maximum iteration count (default: 3). If all iterations fail, p07b marks the gate as failed and the run halts.

### What domains are supported?

`general`, `fintech`, `healthcare`, `saas`, `ecommerce`, `logistics`, `edtech`. The domain selection triggers domain-specific compliance guardrails at intake and CI/CD phases.

---

## LLMs and Models

### What LLMs are supported?

| Tier | Provider | Model | Used for |
|------|----------|-------|----------|
| Primary | Anthropic | claude-sonnet-4-6 | All phases by default |
| Secondary | Google | Gemini 2.5 Flash | Fallback when Anthropic is unavailable |
| Tertiary | Amazon Bedrock | claude-sonnet-4-6 (cross-region) | Enabled via `BEDROCK_ENABLED=true` |
| Quaternary | OpenRouter | Configurable | Fallback |
| Local | Ollama | qwen2.5-coder:3b (default) | Air-gapped mode |

LLM routing is configured per-phase. Heavy tasks (codegen, security review) default to the primary model. Light tasks (gate evaluation, summarisation) can use a faster/cheaper model.

### Can I use my own Anthropic API key?

Yes. Set `ANTHROPIC_API_KEY` in your `.env`. You can also configure per-org LLM settings from the admin panel, allowing different organisations to use different API keys and models.

### How is LLM cost calculated?

Every LLM call records input tokens, output tokens, and estimated cost in USD based on current Anthropic/Google pricing. These records are aggregated per phase, per run, and per organisation. You can view the breakdown in the **Billing** tab.

---

## Code Sandboxing

### How is generated code executed safely?

The sandbox guard (`core/sandbox/guard.py`) applies several controls before executing any generated code:

- **Import stripping**: dangerous imports (`os.system`, `subprocess`, `socket`, etc.) are removed or replaced with no-ops
- **Filesystem restriction**: generated code can only write to its project directory (`/var/aetheros/runs/<run_id>/project/`)
- **Process isolation**: the generated app runs as a separate subprocess with a non-root user
- **Resource limits**: CPU and memory limits are applied via `resource.setrlimit`
- **Network restriction**: outbound network calls from the generated app are blocked by default (configurable)

### Can generated code access the AetherOS database or secrets?

No. The generated app runs in a separate process with no access to AetherOS environment variables or the platform database.

---

## Security Model

### How is multi-tenancy enforced?

Every database table that contains org-specific data has an `org_id` column. All queries are scoped to the authenticated organisation's `org_id`. The `X-Org-ID` request header is validated in middleware — a mismatch is a 403. There is no "super-query" path in the codebase that retrieves data across organisations without admin authentication.

### What authentication methods are supported?

- Email/password with bcrypt hashing
- TOTP MFA (pyotp, compatible with Google Authenticator and Authy)
- SAML SSO (python3-saml, compatible with Okta, Azure AD, Google Workspace)
- OAuth2 social login
- SCIM v2 automated user provisioning for enterprise IdPs
- JWT refresh token rotation (short-lived access tokens, long-lived refresh tokens stored server-side)

### What is the zero-trust execution secret?

`AETHER_ONE_ZT_SECRET` is a shared secret used to authenticate inter-service calls between the gateway and internal execution components. It must be set — there is no fallback default.

### How are secrets managed?

All secrets are environment variables. No secrets are hardcoded in the codebase. The `.env` file is gitignored. Production secrets should be injected via a secrets manager (AWS Secrets Manager, Vault, etc.) rather than stored in `.env`.

---

## Billing

### How does billing work?

AetherOS uses Razorpay for payment processing. The flow is:

1. User selects a plan → `POST /billing/create-order` creates a Razorpay order
2. User completes payment in the Razorpay checkout modal
3. Client sends payment details to `POST /billing/verify` — server-side signature verification
4. On success, the org's plan is upgraded in the database
5. Razorpay webhook (`POST /billing/webhook`) handles async payment confirmations and refunds

Plan limits (trial: 3 runs, pro: 50 runs/month, enterprise: unlimited) are enforced at `POST /factory/start`.

### What payment methods are supported?

All methods supported by Razorpay: credit/debit cards, UPI, net banking, wallets (India). International cards are supported on Razorpay's international payment gateway.

---

## Self-Hosting

### Can I self-host AetherOS?

Yes. Requirements:

- Python 3.11+
- PostgreSQL 15+ (primary datastore)
- Redis 7+ (message bus and cache)
- An Anthropic API key (or configure Ollama for fully local operation)

Quick start:
```bash
git clone <repo> aether_os && cd aether_os
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Fill in required values
alembic upgrade head
uvicorn gateway.api:app --host 0.0.0.0 --port 8000 --workers 4
```

### Is there a Docker image?

A `Dockerfile` is included in the repository root. Build with:
```bash
docker build -t aetheros:latest .
```

A `docker-compose.yml` is also provided for local development, including PostgreSQL and Redis services.

### Can I run AetherOS air-gapped (no external API calls)?

Yes. Set `OFFLINE_MODE=true` and configure Ollama as the LLM provider. In this mode, all LLM calls are routed to your local Ollama instance. No data leaves your network.

### What are the minimum server specifications?

For a single-node production deployment: 4 vCPU, 8 GB RAM, 50 GB SSD. For concurrent pipeline runs (3+ simultaneous), scale to 8 vCPU / 16 GB RAM.

---

## Data and Privacy

### Where is generated code stored?

By default, generated project files are stored in `/var/aetheros/runs/<run_id>/` on the server filesystem. The database stores metadata (run status, phase results, costs) but not file content. You can configure an external object store (S3-compatible) by setting `ARTIFACT_STORE_URL`.

### What data does AetherOS send to Anthropic/Google?

Your requirement text and generated code artifacts are sent to the configured LLM provider for processing. Review the provider's data processing agreements before using AetherOS with sensitive data. LangSmith telemetry is opt-in and requires explicit user consent before activation.

### Does AetherOS retain generated code after a run?

Artifacts are retained for 30 days by default (configurable via `ARTIFACT_TTL_DAYS`). After TTL expiry, the artifact files are pruned. Database run metadata is retained indefinitely unless explicitly deleted.
