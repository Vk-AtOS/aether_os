# Load testing

Two tools, same targets:

* `harness.py` - stdlib only, runs anywhere, writes a recorded JSON result (below).
* `locustfile.py` - richer scenarios (Browse/Active/Admin users), needs `pip install locust`.

```
# 1. a server you may hammer (local or staging; never production) and seeded users
python3 tests/load/seed_load_users.py --host http://127.0.0.1:8000 --count 220
# 2. run
python3 -m aether_os.tests.load.harness --host http://127.0.0.1:8000 --users 200 --duration 120 \
    --email loadtest_0@example.com --password 'LoadTest@1234'
```

## Result format (`results/<UTC>.json`, `schema_version` 1)

`started_at, host, users, duration_s, think_s, client{python,os}`, `total{requests, errors,
error_rate, p50_ms, p95_ms, p99_ms, mean_ms, rps}` and `endpoints{<path>: same stats}`.
An error is a network failure/timeout or HTTP >= 500 (429 is the rate limiter working, not an error).
Exit code 1 if p95 or error rate breach the thresholds (defaults: p95 1500 ms, errors 2 %).
Commit result files you want to keep as evidence under `docs/load/` with the commit of the code tested.

## Capacity statement

**Target:** 1000 engineers (about 200-300 concurrently active, think time 1-5 s, a handful of
pipeline runs in flight per organisation) on one API node group behind nginx, PostgreSQL via
PgBouncer, Redis with `noeviction`.

**Measured: nothing yet.** No run of this harness against a production-like stack has been
recorded; this repository was prepared without access to one. Until a result file exists, the
supported figure is the design limit below, not a measurement:

| Resource | Design limit | Where it is set |
|---|---|---|
| DB connections | workers x (DB_POOL_SIZE 3 + DB_MAX_OVERFLOW 7) per node, PgBouncer `max_client_conn` 1000 | `core/db.py`, `deploy/pgbouncer.ini` |
| Query time | 30 s (`DB_STATEMENT_TIMEOUT_MS` / PgBouncer `query_timeout`) | `core/db.py` |
| Pipeline runs in flight | `PIPELINE_MAX_CONCURRENT` (2) per node, plan limit per organisation | `orchestrator/run_state.py`, `core/policy/rules.py` |
| Quality scoring | 2 at a time per worker | `core/quality/score_async.py` |
| SQS jobs in flight | `SQS_MAX_INFLIGHT` per process | `core/queue/pipeline_consumer.py` |
| Per-IP request rate | 600 req/min + burst 100 (nginx `zone=api`) | `deploy/nginx.conf` |

**Acceptance for "1000 engineers":** a recorded run with `--users 300` for 10 minutes against
staging with p95 < 1500 ms and error rate < 2 %, plus a 15 minute soak at 100 users with no
growth in RSS or DB connections. Record the file, then replace this paragraph with the numbers.
