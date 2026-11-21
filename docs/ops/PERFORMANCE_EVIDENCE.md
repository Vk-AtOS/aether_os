# Performance evidence (KAN-193)

Every number on this page was measured on 22 Nov 2026 against the production install
(https://3-105-82-63.sslip.io: one m7i-flex.large host with 2 vCPU and 8 GiB, RDS PostgreSQL 15 db.t4g.small, Sydney) or
read from CI. It replaces the earlier unrecorded claims (load test "p95 = 240 ms at 50 users", "7-10 minute builds",
"647 passing tests"; see CHANGELOG corrections). Re-measure after any change of host size or model provider.

## API latency and throughput (k6 0.54, run on the production host, 22 Nov 2026)

| Scenario | Load | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|
| `GET /health`, straight to the API | 20 concurrent virtual users, 30 s, about 850 req/s | 18.9 ms | 38.6 ms | 56.8 ms | 0 of 25,678 |
| `GET /api/factory/runs`, authenticated, database-backed | 8 req/s constant arrival, 60 s | 20.0 ms | 24.4 ms | 69.7 ms | 0 of 481 |
| `GET /api/health` through nginx + TLS on the public name | 8 req/s, 60 s | 2.4 ms | 2.8 ms | 3.6 ms | 0 of 481 |

The rate limits engage as designed. One client IP sending about 17,000 req/s through nginx is rejected by
`limit_req` (600 requests per minute per IP). One user above the application's per-user limit gets 429. So higher
throughput needs many clients or users, not one load generator. The load harness for that is in `tests/load/`
(locust).

## Pipeline duration (real model: NVIDIA Nemotron 3 Ultra via the OpenAI-compatible endpoint)

Measured from `pipeline_events` on production acceptance runs 2 and 3 and testbed runs 8 and 9. Gate approvals were
given by a script within about 15 s, so human review time is excluded.

| Stage | Typical duration | Notes |
|---|---|---|
| s01 intake (research, requirements, spec) | 2 to 4 min | includes Gate 1 and spec approval |
| s02 architecture | 0.5 to 2 min | |
| s03 backend (codegen, sandbox build, live `/health` probe) | 6 to 8 min | passed on all four runs after PRs #17, #32 and #40 |
| s04 frontend (codegen, `npm install` about 35 s, `vite build`, fix loop) | 16 to 18 min with 3 gate attempts | fixes in PRs #34, #41 and #43 |

Model calls per run, s01 to s04: about 50 (43 to 44 heavy and 4 to 7 light calls on runs 2 and 3).

## Cost per run

The NVIDIA endpoint used for these runs had no charge (trial key, no card attached), so the measured model cost per
run was USD 0. With a paid provider, cost is about 50 calls per s01 to s04 run multiplied by that provider's price per
call. The per-organisation spend caps (KAN-116: trial 5, starter 50, pro 200 USD a month) bound it. Infrastructure for
the single-host install is about USD 100 to 150 a month (see `deploy/terraform/aws/environments/prod-single`).

## Test suite

CI on main, 22 Nov 2026: 2578 tests passed (PR #41 run). `scripts/repo_stats.py --check` keeps the collected count in
SALE_READINESS.md in step with the code.
