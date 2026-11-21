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

## Not covered

Only whole-service stops. Slow responses, network partitions and a full disk are not injected (KAN-52 slow-walk item).
