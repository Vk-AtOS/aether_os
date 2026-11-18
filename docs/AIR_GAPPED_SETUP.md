# Air-Gapped / Offline Setup

`OFFLINE_MODE=true` limits the LLM model chain to a local Ollama server. It does not turn off every outbound network call in the application. Read "What OFFLINE_MODE does not do" before you rely on it. This file was checked against the code at commit `e5c23fd`.

## Requirements
- Ollama installed on the machine, with at least one model pulled, for example `ollama pull llama3.1:8b`.
- Python 3.10 or newer (`pyproject.toml:11`). CI runs 3.11 (`.github/workflows/ci.yml:60`).
- PostgreSQL and Redis reachable from the host. Their images and the Python packages must already be on the machine: nothing in the repository builds an offline package mirror or image bundle.

## Setup
1. Install Ollama: https://ollama.ai/download
2. Pull a model: `ollama pull llama3.1:8b`
3. Copy `.env.example` to `.env`. It has a section "AIR-GAPPED / LOCAL-ONLY MODE" with commented lines you can enable.
4. Set `OFFLINE_MODE=true` and `PRIMARY_LLM=ollama`.
5. Start the API from the directory that contains the `aether_os` checkout:
   `uvicorn aether_os.gateway.api:create_app --factory --host 0.0.0.0 --port 8000`
   (the same command as `deploy/aetheros.service` and `Dockerfile:51`; `uvicorn aether_os.gateway.api:app` also works).

## Minimal .env for offline mode

```bash
OFFLINE_MODE=true
PRIMARY_LLM=ollama
OLLAMA_MODEL=llama3.1:8b
OLLAMA_TIMEOUT=300
AETHER_SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
AETHER_ONE_ZT_SECRET=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
AETHER_ADMIN_EMAIL=<admin email>
AETHER_ADMIN_PASS=<strong password>
CORS_ORIGINS=http://localhost:3000
FRONTEND_URL=http://localhost:3000/dashboard
DATABASE_URL=<postgres url>
REDIS_URL=<redis url>
```

Where each variable is read:
- `OFFLINE_MODE`, `PRIMARY_LLM`, `OLLAMA_MODEL`, `OLLAMA_TIMEOUT`: `core/model_router_providers.py:91-103`. With `OFFLINE_MODE=true` the defaults are model `llama3.1:8b` and timeout 300 s.
- `AETHER_SECRET_KEY`, `AETHER_ONE_ZT_SECRET`: checked at start in `main.py:65-68`; `AETHER_SECRET_KEY` is also the HS256 signing fallback in `gateway/auth.py:89`.
- `AETHER_ADMIN_EMAIL`, `AETHER_ADMIN_PASS`: the only variables the admin seed reads (`core/seed.py:28,34`). The old names `AETHER_ADMIN_USER` and `AETHER_ADMIN_PASSWORD` are not read by the application. `RETRIEVER` is read nowhere either.
- `CORS_ORIGINS`, `FRONTEND_URL`: required by `docker-compose.yml:85-86`.

Ollama server address: the model router calls Ollama through the config key `llm.ollama_base_url` (`core/llm/providers.py:235`). It comes from the YAML file named by `AETHER_CONFIG_PATH` (default `~/.aether_os/config.yaml`, `core/config/loader.py:29-31`) and defaults to `http://localhost:11434`. The environment variable `OLLAMA_BASE_URL` is read only by the council reviewer (`core/council/council_reviewer.py:323`). If Ollama is not on localhost, set both.

## What OFFLINE_MODE does
The model router returns a chain with only the Ollama entry (`core/model_router_providers.py:91-98`). Anthropic, Bedrock, Gemini and OpenRouter are not in the chain, so no LLM request goes to them.

## What OFFLINE_MODE does not do
- It is read in one place only (`core/model_router_providers.py:91`). No other code checks it.
- The password safety check on registration and password change calls the HaveIBeenPwned range API (`core/guardian/password_shield.py`). Registration continues when the check fails (`gateway/routers/auth_router.py`, "Fail open").
- Other features can make outbound calls when they are configured: LangSmith tracing, Sentry, Stripe, Razorpay, e-mail, OAuth and connectors. Leave them unconfigured. A full list of outbound calls was not produced, so "100% offline" is not verified.
- The embedding path tries other providers before Ollama (`core/llm/client.py:409`); behaviour offline was not tested.

## Performance
Speed on CPU, run time of a full pipeline and quality of the output with local models: not measured. The previous version of this file gave tokens per second, a 45 to 90 minute run time, a "tested configuration" on named hardware and "all 20 phases complete". None of that is backed by a test or a benchmark in the repository, so it was removed. The pipeline has 12 stages (`orchestrator/phase_sequence.py`).

## Troubleshooting

**"Connection refused" on port 11434:** Ollama is not running. Start it with `ollama serve`.

**Slow responses:** use a smaller model. Raise `OLLAMA_TIMEOUT` if calls time out (default 300 s in offline mode).

**Out of memory:** use a smaller model, for example `OLLAMA_MODEL=qwen2.5-coder:3b` (the default model of the non-offline chain).

**Model not found:** run `ollama pull <model_name>` before starting AetherOS. The router has no check for this at start; the error shows when the first call is made.
