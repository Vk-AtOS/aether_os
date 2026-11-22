# AetherOS - Cost Model

Checked against the code at commit `e5c23fd`. This file lists only what can be read from the code: the price
table, the spend cap and the plan defaults. No recorded run exists: `benchmarks/results/` holds only
`.gitkeep`. So the cost, token count and duration of a pipeline run, infrastructure cost and margins are
**not measured**. Earlier versions of this file gave per-run dollar ranges, "about 21 calls", run times, runs
per hour and a 93-95% margin; none of those had a source and they are removed.

## What the pipeline calls

The pipeline has 12 stages, not 21 phases (`orchestrator/phase_sequence.py:90-103`). Each stage calls one or
more phase agents, and phases call the model router an unknown number of times. Calls per run: not measured.
(Some stage docstrings give "~5 calls" or "~3 calls"; these are the authors' estimates, not recordings.)

## Price table in code

Two tables exist and they differ.

`core/llm/budget.py:61-80` (used to compute `estimated_cost_usd`, which the spend cap reads), USD per million tokens:

| Model key | Input | Output |
|-----------|-------|--------|
| `claude-sonnet-4-6` | 3.00 | 15.00 |
| `claude-haiku-4-5-20251001` | 0.25 | 1.25 |
| `gemini-2.5-flash` | 0.15 | 0.60 |
| `gemini-2.5-pro` | 1.25 | 5.00 |
| any other model (`default`) | 3.00 | 15.00 |

`core/llm/client.py:186-203` (used to compute `runs.cost` per call, USD per 1K tokens, shown here per million):
Bedrock `amazon.nova-pro-v1:0` 0.80 / 3.20, `amazon.nova-lite-v1:0` 0.06 / 0.24,
`anthropic.claude-3-5-sonnet-20241022-v2:0` 3.00 / 15.00, `anthropic.claude-3-haiku-20240307-v1:0` 0.25 / 1.25,
`us.meta.llama3-3-70b-instruct-v1:0` 0.72 / 0.72, `claude-sonnet-4-6` 3.00 / 15.00,
`claude-haiku-4-5-20251001` 0.25 / 1.25, `gemini-2.5-pro` 1.25 / 5.00, `gemini-2.0-flash` 0.15 / 0.60.
A model not in this table (for example an OpenRouter model) is charged a flat 1.00 per million tokens
(`client.py:255-256`). Output tokens are estimated as `len(response) // 4` (`client.py:241`), so recorded cost is
an estimate. Whether these rates match the providers' current price lists: not verified.

Which model a run uses first depends on `PRIMARY_LLM`, default `bedrock` (`core/model_router_providers.py:100`).
The default chain is Bedrock Nova Pro, then a Bedrock fallback model if it differs, then Anthropic and Gemini if
configured, then OpenRouter models, then Ollama (`model_router_providers.py:131-150`). A configured Anthropic key
is not the default first choice.

## Timeouts and retries (`core/model_router_providers.py`)

- One attempt per model: `retry_count` is 1 for every entry (lines 120-136), so a transient error is not retried
  on the same model unless the router's self-critique path applies (`core/model_router.py:431-442`).
- Timeouts: Anthropic 60 s, Gemini 45 s, OpenRouter 60 s per model, Bedrock `BEDROCK_TIMEOUT` (default 60 s),
  Ollama `OLLAMA_TIMEOUT` (default 120 s; 300 s in offline mode).
- A timeout or a hard error (bad key, model not found) moves to the next model in the chain; rate-limit and
  overload errors are classed as retry (`model_router_providers.py:157-180`). Between models the router waits
  before the next call (`model_router.py:269-283`).
- Models marked dead by a failure are skipped for a time (`_DEAD_MODELS`, `_dead_ttl()`).
- Free OpenRouter models (`:free`) are removed from the chain unless `ALLOW_COMMUNITY_LLM` is set, and all
  OpenRouter models are removed for prompts classed as sensitive (`model_router.py:203-210`). A `trial` plan is
  further limited to free-tier models (`model_router.py:233-255`). Fallback to a model with a different price changes the
  cost of a call.

## Spend cap per organisation

Before each model call, `core/llm/guard.py:admit()` runs: global kill switch, organisation exists and is not
disabled, plan known, then `check_budget` (`core/llm/budget.py:133-160`). It refuses the call when either the
monthly token allowance or the monthly USD allowance would be passed, counting the worst-case cost of the call
(`guard.py:36-39`). It sends a one-time in-app notification at 80%, and returns a hint to use Haiku from 85%. It
blocks at 100%. An unknown plan, a missing organisation or a database error refuses the call. Calls with no
organisation are not capped per organisation (platform plan, USD 500 default, listed below).
A single organisation can have its own USD cap: `Organisation.llm_monthly_cap_usd` (`core/models.py:41`).
Usage is stored in `token_budget_records`, one row per organisation and month.

Plan defaults (`core/llm/plans.py:22-30`). The file says these defaults still need the owner's review.

| Plan | Tokens per month | USD per month |
|------|------------------|---------------|
| free | 500,000 | 2 |
| trial | 500,000 | 5 |
| starter | 5,000,000 | 50 |
| growth | 25,000,000 | 250 |
| pro | 25,000,000 | 250 |
| enterprise | 999,999,999 | 2,000 |
| platform (no organisation) | 999,999,999 | 500 |

The "about 5 / 50 / 250 runs per month" notes in the docstring of `core/llm/budget.py:9-12` have no recorded
basis: runs per plan are not measured.

## Concurrency

The code limits concurrent pipelines per process with a semaphore set by `PIPELINE_MAX_CONCURRENT` (default 2)
(`orchestrator/factory_pipeline.py:148`), and per organisation by `MAX_CONCURRENT_RUNS_PER_ORG` (default 5) and
`MAX_STARTS_PER_ORG_PER_HOUR` (default 20) (`core/rate_limiter.py:161-165`). A run times out after
`PIPELINE_TIMEOUT_MINUTES` (default 120, `core/run_limits.py`). Throughput in runs per hour: not measured.
Run duration: not measured.

## Not measured

- Cost per run, tokens per run, LLM calls per run, per provider.
- Run duration by app size.
- Infrastructure sizing and monthly cost. Earlier tables of server, database and Redis prices had no source in
  the repository (deployment files exist in `deploy/`, `helm/` and `docker-compose.yml`, but no measured load).
- Gross margin, revenue per plan and price per plan. The code holds no price list for subscriptions that was
  checked in this review.
