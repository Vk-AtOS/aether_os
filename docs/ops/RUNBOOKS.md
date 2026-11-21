# Runbooks, one per component (KAN-51)

Each section: **Symptoms** (what you see or what alerted), **Checks** (commands, read-only), **Fix**, **Escalate**. The alert
rules in `deploy/observability/alerts.yml` link to the headings below; a test fails if a link breaks.
Commands assume the compose deployment (`docker compose ...`); for the VPS use `systemctl`/`journalctl`, for Kubernetes
`kubectl -n aetheros`. Never paste secrets into tickets. The older single-page `RUNBOOK.md` at the repository root stays for
history; where it disagrees with this page, this page is current.

Who to call: the on-call contact and the owner's phone are kept in the secret manager entry `oncall` (not in this repository).

## Quick triage

1. `curl -s https://<app>/readyz`: `{"ready": false, "degraded": [...]}` names the component. 503 means this instance serves nothing.
2. `GET /system/components` (admin token): breakers, bulkheads, component status. The dashboard status pill shows the same.
3. Find a request everywhere with its trace id: the browser shows `X-Trace-Id` on every response; search that id in the API logs,
   in Velaris logs (`request_id`) and in the ledger entry metadata (`trace_id`).

## API

**Symptoms:** `AetherOSApiDown`, `ErrorRateSpike`, `SlowRequests`; 5xx in the dashboard; `/healthz` fails.
**Checks:** `docker compose ps api`; `docker compose logs --tail=200 api | grep -i error`; `curl -s localhost:8000/healthz`
(process alive) vs `/readyz` (dependencies); memory: `docker stats --no-stream api`.
**Fix:** `/healthz` fails: `docker compose restart api` (stop grace is 60 s, in-flight requests finish). `/healthz` ok but
`/readyz` 503: it is a dependency, go to Postgres or Redis. 5xx after a deploy: roll back (`git revert` the deploy commit,
redeploy; migrations are forward-compatible by rule, see Postgres). OOM kills (`docker inspect api | grep OOMKilled`): lower
`--workers` or raise the memory limit, then find the leak from the trace ids of the slowest requests.
**Escalate:** crash loop after rollback, or data written wrongly: stop the API, keep the database, call the owner.

## Postgres

**Symptoms:** `AetherOSNotReady` with `degraded: [postgres]`, logs show `OperationalError`/pool timeouts, `/readyz` 503.
**Checks:** `docker compose exec db pg_isready -U aether_user -d aether_os`; connections:
`select count(*), state from pg_stat_activity group by 2;` (pool is `DB_POOL_SIZE`+`DB_MAX_OVERFLOW` per worker); disk:
`df -h`; long queries: `select pid, now()-query_start, left(query,80) from pg_stat_activity where state<>'idle' order by 2 desc limit 5;`.
**Fix:** connection exhaustion: restart the API (it reconnects), then lower workers or add PgBouncer (`deploy/pgbouncer.ini`,
`DB_PGBOUNCER=true`). Disk full: free space or grow the volume first, then restart Postgres. Corruption or loss: **restore**
(below). Migrations: `python scripts/db_migrate.py` (empty database: create and stamp; existing: `alembic upgrade head`). The API
refuses to start on a schema that is not at head: run the migrate step, do not set `AETHER_DB_CREATE_ALL` in production.
**Escalate:** any restore from backup, any manual `DELETE`/`UPDATE` of production rows: owner approval.

### Backup and restore (read this before you need it)

`BackupTooOld` fires at 26 hours: run `systemctl status aetheros-backup.timer` and read `/var/log/aetheros/backup.log`, then run `deploy/scripts/backup.sh` by hand. The API reads the dump directory read-only (`BACKUP_DIR`, default `/var/backups/aetheros`, mounted in docker-compose); if `aether_backup_age_seconds` is absent from Prometheus the directory is not mounted into the API.

* Backups: `deploy/scripts/backup.sh` (custom-format `pg_dump`, daily by `deploy/aetheros-backup.timer`). Managed Postgres also
  has point-in-time recovery: prefer it for "undo the last hour".
* Signed ledger checkpoints: copy them out of the database's reach with `CHECKPOINT_DEST=... bash deploy/scripts/backup_checkpoints.sh`
  (daily, after the backup). Only the public key is copied.
* **Drill (monthly, and before every release that touches migrations):**

      python3.11 scripts/restore_drill.py --dump <latest .dump> --admin-url postgresql://<user>@<scratch host>/postgres \
          --anchor-file <the separately kept ledger_anchors file> --role <low-privilege role> --note "monthly drill, <who>"

  `DRILL_ROLE_PASSWORD` carries the role's password (never put it on the command line); the role must have no SUPERUSER/CREATEROLE/CREATEDB, it owns the scratch database and does the restore, and dumps with event triggers or untrusted-language functions are refused. An empty or missing anchor file is refused. It restores into a scratch database on a server that is **not production**, checks the Alembic head, the core tables, every
  audit chain, and the chains against the external checkpoints, then drops the scratch database. The record
  (`docs/ops/drills/restore-<UTC>.json`) holds seconds per step: that is the measured recovery time. Commit the record.
  `matches_external_anchors=false` ("tail truncated") means the backup is older than the newest checkpoint: use a newer backup
  or accept the loss of the ledger tail knowingly (owner decision).
* **Real restore:** stop the API (`docker compose stop api preview`), restore into a NEW database (`createdb`, `pg_restore --no-owner -d`),
  run the drill's verify against it, only then point `DATABASE_URL` at it (or swap names), start the API, run `scripts/smoke_test.sh`.
  Keep the damaged database until the owner agrees to drop it.
* Targets: RPO 15 minutes with PITR (24 h with the daily dump alone), RTO 60 minutes for one organisation.
  **Measured (AWS, 21 Nov 2026, `docs/ops/drills/restore-20261121T132843Z.json`):** a 2.6 GB database (4 million pipeline
  events; 244 MB compressed dump) took 35 s to dump with the scheduled `aetheros-backup.service`, 1 s to fetch from S3 and
  329 s to restore into RDS PostgreSQL 15 on db.t4g.micro (the smallest class), plus 1 s to verify every chain against the
  external checkpoints: about 6 minutes in all, well inside the 60-minute RTO. Restore time grows roughly with database size;
  a larger instance class restores faster.
* Compose deployments: install the timer with a drop-in that sets `COMPOSE_DIR`, `BACKUP_REMOTE` and `CHECKPOINT_DEST`
  (see `deploy/scripts/backup.sh`); run the drill with `--anchor-file` AND `--public-key` (both from the checkpoint copy).

## Redis

**Symptoms:** `ComponentDegraded{component="redis"}`; `/readyz` 503 when `REQUIRE_REDIS=true` (production).
**What breaks:** every authenticated request answers 503 while Redis cannot be reached: the access-token revocation check fails
closed (`gateway/dependencies.py`, `assert_access_token_live`), by design, so a revoked token can never be accepted because the
store was down. Unauthenticated endpoints (`/healthz`, `/readyz`, public pages) keep answering. Rate limits fall back to per-process
memory and SSE/pause/cancel to single-process mode, so run Redis with a replica and treat an outage as an incident.
**Checks:** `docker compose exec redis redis-cli -a "$REDIS_PASSWORD" ping`; `info memory`; `config get maxmemory-policy` must be
`noeviction` (security keys must never be evicted).
**Fix:** restart Redis (`docker compose restart redis`); the API reconnects within 5 s. Memory full with `noeviction` means writes
fail loudly: raise `maxmemory`, find the key family growing (`--scan --pattern '*' | cut -d: -f1 | sort | uniq -c`).
Losing Redis's data loses revocation entries: after a data loss, force everyone to sign in again by rotating the signing key (owner decision).
**Escalate:** Redis down more than 15 minutes in production (rate limits are weakened for everyone).

## Velaris

**Symptoms:** `CircuitBreakerOpen{name="velaris"}`, `BulkheadRejecting`, dashboard shows `Degraded: velaris`, Velaris pages answer 503.
AetherOS itself keeps serving; only Velaris features are affected (by design).
**Checks:** `docker compose ps velaris`; `docker compose exec api python scripts/velaris_smoke.py --org <org id>` (one signed
request; exit 0 = accepted); Velaris readiness: `docker compose exec velaris python /app/healthcheck.py 8730 /readyz` (503 = data
volume unwritable or under 50 MB free); logs: `docker compose logs velaris | grep -E 'refused|unhandled|audit_unavailable'`.
**Fix:** `403 wrong_organisation`: `VELARIS_ORG` differs from the AetherOS org id. `401`: the shared secret or the identity key pair
does not match (keys are the owner's; rotate together). `audit_unavailable`/readyz 503: free disk or fix volume permissions
(uid 10001, mode 0700). Breaker open but Velaris healthy: it closes itself after 30 s and one good probe call. Data loss:
restore with `deploy/backup/velaris_backup.py restore` then run `deploy/backup/restore_drill.py --archive ...` (record it).
One worker only: do not scale Velaris API replicas (replay cache and rate counters are per process).
**Escalate:** trace verification fails (`GET /trace/verify` not ok): the audit chain was altered or damaged; stop writes, call the owner.

## Queue

**Symptoms:** `DeadLetteredJobs`; runs stay `queued`; `SQS_QUEUE_URL` set but nothing consumed.
**Checks:** `GET /system/dead-letters` (admin; shows run ids and reasons, your organisation's only unless superadmin);
`aws sqs get-queue-attributes --queue-url $SQS_QUEUE_URL --attribute-names All`; consumer log lines `SQS consumer:`.
**Fix:** a job lands in the dead-letter queue after 3 receives (`SQS_MAX_RECEIVES`) or 5 (queue redrive). Read the run's failure
message in the dashboard; fix the cause (bad input, provider outage); then re-queue the run from the dashboard (not by replaying
the raw message). Queue depth growing: raise `SQS_MAX_INFLIGHT` / API task count; the per-task cap is `PIPELINE_MAX_CONCURRENT`.
**Escalate:** the same run dead-letters twice after a fix.

## Approvals

**Symptoms:** `ApprovalOlderThanReminder` (an approval waited more than 4 h).
**Checks:** the approver's inbox (`GET /prime/inbox`); `aether_approvals_pending` and `aether_approval_oldest_pending_seconds` in Prometheus.
**Fix:** nudge the approver or the active deputy (Delegations); an expired request must be re-submitted, it cannot be revived.
Nothing is auto-approved: never edit rows to unblock.
**Escalate:** an approver who left the company: the org owner reassigns the delegation.

## Model gateway

**Symptoms:** `OrganisationAtBudget80`; `ComponentDegraded{component="models"}`; runs fail with `LLMUnavailable`; budget errors.
**Checks:** `GET /system/components` (`models.open_breakers`); router log lines `circuit-breaker OPEN`; provider status pages.
**Fix:** provider returning 5xx: nothing to do, the breaker skips it for 30 s at a time and the fallback chain serves (`ROUTER_BREAKER_FAILURES`,
`ROUTER_BREAKER_OPEN_SECONDS`). Bad key: the breaker opens for 10 minutes for that scope; fix the key in Settings. 80% budget: tell
the organisation; the hard stop is at 100% by design; raising a cap is a plan decision for the owner. Kill switch: see `core/llm/budget.py`.
**Escalate:** `ModelCallsRefused` / `ModelProvidersAllDown` (label `reason`: `no_model` = nothing configured or allowed for this data/plan, `chain_exhausted` = every provider failed, `admission` = kill switch, unknown org or plan, budget stop); every provider down; unexpected spend growth (`aether_llm_cost_usd_total`).

## Sandbox

**Symptoms:** `SandboxStartFailures`; generated apps do not start; `sandbox: refusing to run generated code`; `docker: not found` in API logs.
**Checks:** `docker compose exec api docker version` (needs the socket and `DOCKER_GID`); `docker image inspect aether-sandbox:1`;
the isolation probe message in the log (host firewall rules from `core/sandbox/host_firewall.sh` missing).
**Fix:** build the image (`docker build -f core/sandbox/Dockerfile -t aether-sandbox:1 core/sandbox`); apply `host_firewall.sh` on the
Docker host; orphaned containers: `docker ps --filter label=aether.run` and `docker rm -f` those whose run is gone.
**Escalate:** any sign a generated app reached the host or the platform network: stop the sandbox host, call the owner.

## Guardian

**Symptoms:** `GuardianTamperDetected`; a critical `file_tamper` event in the guardian event list; log line `Guardian: TAMPER DETECTED`.
**Checks:** which file (`detail.file`) and whether you changed it (a deploy changes hashes on purpose); the version-control diff of that file
on the host; `aether_guardian_tamper_total` in Prometheus.
**Fix:** a deploy you made: restart the API so the baseline is rebuilt. Not yours: treat as an incident, keep the changed file for
evidence, restore it from the repository, rotate secrets the file could read. The guardian never restores a database on tamper, by design.
**Escalate:** any unexplained change: call the owner before restoring anything.

## Preview

**Symptoms:** previews blank or refused; preview server will not start ("preview server refuses to start").
**Checks:** `curl -s http://127.0.0.1:8100/__preview/health`; `python3.11 scripts/check_preview_origin.py https://<preview domain>`
(wildcard DNS and certificate); `docs/ops/PREVIEW_ORIGINS.md`.
**Fix:** the refusal names the rule broken (origin equals dashboard origin, listed in CORS, secret too short). Certificate near
expiry: renewal timer `aetheros-cert-renew.timer` or cert-manager; run the issue script again if DNS-01 credentials changed.
**Escalate:** a preview ever served on the dashboard origin: treat as a security incident.

## Dashboard

**Symptoms:** blank page after a deploy, assets 404.
**Checks:** the API image contains `dashboard/dist` (`docker compose exec api ls dashboard/dist | head`); browser console.
**Fix:** rebuild the image (the build stage compiles the dashboard); clear the CDN cache; hard reload.
**Escalate:** a rebuilt image still serves a blank page: roll back to the previous image digest and call the owner.

## Ledger

**Symptoms:** `AUDIT ANCHOR FILE CHECK FAILED` in logs; `/prime/ledger` verification not ok.
**Checks:** `GET /prime/ledger/anchor/export`; compare with the copy from `backup_checkpoints.sh`.
**Fix:** none by editing: a failing chain means history was altered or the database was rolled back. Preserve the database and the
external checkpoints, run the restore drill against the newest backup to find the last good state.
**Escalate:** immediately, to the owner.

## Images

Base images are pinned by tag and digest (`Dockerfile`, `core/sandbox/Dockerfile`, compose). To update: pick the new tag, read its
digest (`docker buildx imagetools inspect <image:tag>`), change both, rebuild, run the suite and `docker compose up` on staging first.
A scheduled dependency bot (Dependabot docker ecosystem) should propose these; it is not configured yet.
