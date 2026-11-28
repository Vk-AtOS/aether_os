# Acceptance suite: six request types, checked by behaviour (KAN-266)

Until 28 Nov 2026 the platform had been tested on one prompt (all 35 prod runs were "team task tracker"). The suite builds
six different request types and checks what the generated app actually does, not only that the stages are green.

| id | request | what is checked beyond the pipeline |
|---|---|---|
| `bakery_site` | bakery website | menu list public (200), menu create needs login (401), public contact form POST, admin creates a menu item |
| `consultancy_landing` | marketing site, no accounts | `/` serves a page, no login/register/user endpoints exist |
| `clinic_booking` | appointment booking | public booking form POST, appointments list needs staff login, staff create + status change |
| `support_agent` | customer-support AI agent | chat endpoint returns a non-empty answer from the configured LLM, conversation log needs login, no shell/eval in the agent's tools |
| `task_tracker` | team task tracker (regression) | everything behind login (401), create, read back, todo -> doing -> done |
| `shop_orders` | e-commerce catalogue + orders | catalogue public, orders list needs login, guest order POST, owner manages products |

Every prompt also gets: run status `completed`, every stage passed (a skipped stage fails unless the prompt lists it in
`allow_skipped_stages`), `app_started`, frontend `tsc` + build ok, a clean export (no private keys, `.env`, databases,
`preview_credentials.json` or pipeline stage folders; has `backend/` and `MANIFEST.json`), and zero blocking findings from
`core/rulepacks/report.py` (SKIP while that module is not in the checkout).

## Where the expectations live

`scripts/acceptance/prompts.json`: `defaults` plus one entry per prompt. Endpoints are matched by regex against the
generated app's own `/openapi.json`, because the model names them; a check that finds nothing FAILS with that reason. Bodies
for POSTs are built from the app's request schemas. To add a request type, add an entry (keys are validated by
`validate_expectations`, run by `--validate-only` and by the unit test).

## Run it locally

```
./scripts/local.sh up                       # server :8000, preview server :8100 (needs Postgres, Redis, a real model key)
python3 scripts/acceptance_suite.py --base-url http://127.0.0.1:8000 \
    --email local-e2e@aetheros.test --password "$LOCAL_E2E_PASSWORD" --only task_tracker --build-frontend
```

Add `--probe local` to start the exported backend in a throwaway venv on this machine instead of using the preview origin
(needs pip and network; the app is started with a random secret and a SQLite file).

## Run it against prod

```
ACCEPT_TOKEN=<JWT of a user in the org that owns the runs> \
python3 scripts/acceptance_suite.py --base-url https://<host> --concurrency 2 --max-minutes 60
```

The token is read from the environment only; do not write it to a file. A real build costs model money: run the whole
suite deliberately, or pick prompts with `--only a,b`. Prod previews live on `<run-id>.<preview host>`, so the machine
running the suite must resolve that wildcard host; if it cannot, the behaviour checks FAIL with "could not reach the
running app" and the reason, and `--probe local` is the alternative.

## What it does and does not do

- Starts builds with `mode="autonomous"`. It never approves a gate: a run that waits for a human is reported as
  "stuck waiting for a human gate".
- Polls `GET /factory/runs/{id}`, reads `failed_stages`/`skipped_stages`, `GET /factory/runs/{id}/run-app/status`,
  downloads `GET /factory/runs/{id}/download` and inspects the zip in memory (extracted only for the frontend build or
  `--probe local`, after every member path is checked).
- Frontend build/tsc: from `--build-frontend` (npm install, `tsc --noEmit`, `npm run build` on the export), else from build
  metadata in the run record when present, else SKIP. `--strict` makes every SKIP a failure.
- Writes `docs/acceptance/suite-<UTC>.json` and `.md` (override with `--out`): per prompt, per check, PASS/FAIL/SKIP with
  the real reason. Exit code 0 only when every selected prompt passed; 2 when nothing could be run (no credentials,
  unhealthy server, bad expectation file).

## Offline test

`tests/test_acceptance_suite.py` validates the expectation file and drives the whole flow and report with fakes (no
network, no model): `PYTHONPATH=.. python -m pytest tests/test_acceptance_suite.py`.
