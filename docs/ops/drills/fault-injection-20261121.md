# Fault injection on a real compose stack, 21 Nov 2026 (KAN-52)

Where: AWS testbed (ap-southeast-2), one m7i-flex.large Docker host, `docker compose --profile velaris` from main ff6ce31
plus the fixes on branch infra/aws-staging. Command: `scripts/fault_injection.py --run --token ... --compose-file docker-compose.yml`.
Each service is stopped in turn, probed, and restarted.

## Result after the fixes: every row matches the design (exit 0)

| stopped | healthz | readyz | authed read | velaris | preview |
|---|---|---|---|---|---|
| (nothing) | up | up | up | up | up |
| db | up | refused | refused | refused | up |
| redis | up | refused | refused | refused | up |
| velaris | up | up | up | refused | up |
| preview | up | up | up | up | down |
| api | down | down | down | down | up |

## First run, before the fixes (exit 1)

| stopped | healthz | readyz | authed read | velaris | preview |
|---|---|---|---|---|---|
| (nothing) | up | up | up | refused | up |
| db | up | refused | http 500 | http 500 | up |
| redis | up | refused | refused | refused | up |
| velaris | up | up | up | refused | up |
| preview | up | up | up | refused | down |
| api | down | down | down | down | up |
GAP: stopping (nothing): velaris is 'refused', design says 'up'
GAP: stopping db: authed read is 'http 500', design says 'refused'
GAP: stopping db: velaris is 'http 500', design says 'refused'
GAP: stopping preview: velaris is 'refused', design says 'up'

* Velaris "refused" with nothing stopped: the documented vault key setup left Velaris unable to read its key (fixed: fc4c546),
  plus the testbed's VELARIS_ORG placeholder.
* db down -> HTTP 500: socket.gaierror escaped the 503 handler (fixed: c943337).

## Second run: slow, partition and a full disk (exit 0, every row matches)

Same testbed, main 9ec2baf plus branch ops/kan51-52. Command:
`scripts/fault_injection.py --run --token ... --disk-full /var/lib/docker/aether-fill` (stop, slow, partition, disk full).

| broken | healthz | readyz | authed read | velaris | preview |
|---|---|---|---|---|---|
| (nothing) | up | up | up | up | up |
| db | up | refused | refused | refused | up |
| redis | up | refused | refused | refused | up |
| velaris | up | up | up | refused | up |
| preview | up | up | up | up | down |
| api | down | down | down | down | up |
| slow db | up | refused | refused | refused | up |
| slow redis | up | refused | up | up | up |
| slow velaris | up | up | up | up | up |
| partition db | up | refused | refused | refused | up |
| partition redis | up | refused | refused | refused | up |
| partition velaris | up | up | up | refused | up |
| disk full | up | up | up | up | up |

Gaps found on the way and fixed before this run:

* **Partitioned PostgreSQL hung the first request for over 60 s** (curl gave up; later requests were 503 once the breaker had
  opened). All timeouts were server-side. Fixed with client-side connect and query timeouts (core/db.py, commit
  "a partitioned PostgreSQL hung the first requests").
* The first design rows for "slow" were wrong, not the system: a dependency slowed by 3 s per packet but inside its caller's
  budget (Redis 5 s, Velaris 30 s) keeps serving. The design now says so; a slow PostgreSQL still fails closed.
* Test harness: breakers stay open for their cool-down after a fault is repaired, which blamed the next row for the previous
  fault (disk full showed Velaris refused; by hand it answered 200). The script now waits for full recovery between rows.

## Not covered

Writes under a full disk (only reads are probed); an LLM provider outage (the testbed has no model key, so every row above
already runs with models unavailable: sign-in, reads and Velaris keep working).
