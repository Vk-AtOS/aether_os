# AetherOS Operational Runbook

This file was checked against the code at commit `e5c23fd`. Commands that depend on how your host is set up (service names of PostgreSQL and Redis, paths under `/home`) are marked "host-specific": they could not be checked against the repository. The repository does not run any production host, so no command here was run against one.

## Table of Contents
0. [Database Migrations](#0-database-migrations)
1. [Database Failure](#1-database-failure)
2. [Redis Outage](#2-redis-outage)
3. [LLM Unavailability](#3-llm-unavailability)
4. [Stuck Pipeline Run](#4-stuck-pipeline-run)
5. [OOM (Out of Memory)](#5-oom-out-of-memory)
6. [SSL Certificate Renewal](#6-ssl-certificate-renewal)
7. [Rollback Procedure](#7-rollback-procedure)
8. [Backup & Restore](#8-backup--restore)
9. [SQLite to PostgreSQL](#9-sqlite-to-postgresql)
10. [High Availability (reference design)](#10-high-availability-reference-design)
11. [Velaris public app](#11-velaris-public-app-careers-scheduling-interview-participant-e-sign---kan-128)

---

## 0. Database Migrations

The Alembic history has a single head: `merge_r2_heads` (`python3.11 -m alembic heads` prints `merge_r2_heads (head)`). It merges four earlier heads: `add_org_onboarding`, `add_prime_corrections`, `pgvector_backfill_and_index`, `scim_token_lookup` (`alembic/versions/merge_r2_heads_merge_r2_integration_heads.py:3`). `alembic upgrade head` therefore works. Check again with `alembic heads` after you merge branches: two heads make `upgrade head` fail with "Multiple heads are present".

Use the one migration command the project uses everywhere (`scripts/db_migrate.py`, called by `deploy/deploy.sh:52`, compose service `migrate`):

```bash
# from the directory that contains the aether_os checkout, with DATABASE_URL set
PYTHONPATH=$(pwd) python3.11 aether_os/scripts/db_migrate.py
```

- On an existing database it runs `alembic upgrade head`.
- On an empty database it creates the schema from the models and stamps `head`. It does not replay the history, because the history cannot be replayed from nothing (`scripts/db_migrate.py:1-12`).
- Exit code 0 means the database is at head.

Field encryption: the encrypted column type needs `AETHER_FIELD_KEY` (`core/encryption.py:28`). Without it a per-process key is used, which makes stored values unreadable after a restart (`core/encryption.py:8`; production refuses to start without it, line 35). Set it before the first migration on a real database.

---

## 1. Database Failure

### Detection
```bash
curl -s http://localhost:8000/readyz        # 503 with "degraded" listing the component when Postgres is down
curl -s http://localhost:8000/healthz       # liveness only: does not touch the database
systemctl status postgresql                 # host-specific unit name
```
`/readyz` is not ready when Postgres is down (`core/resilience/health.py:3-4`). `/health` always returns `{"status": "ok", ...}` and does not check the database (`gateway/routers/health_router.py:34-42`).

### Recovery steps (host-specific)
1. Check that the Postgres process runs: `ps aux | grep postgres`.
2. Restart it: `systemctl restart postgresql`.
3. Check for a full disk: `df -h`.
4. If the data is lost, restore from backup (Section 8).

### Impact while down
Authenticated requests read the user row from the database on every call (`gateway/dependencies.py:60-70`), so they fail. The exact status code per route was not measured.

---

## 2. Redis Outage

### Detection
```bash
curl -s http://localhost:8000/readyz
redis-cli -a "$REDIS_PASSWORD" ping         # host-specific; in compose: docker compose exec redis redis-cli ...
```

### Recovery steps
1. Restart Redis (host-specific unit name, or `docker compose restart redis`).
2. Verify `PONG` and the `/readyz` result.

### What the code does while Redis is down
- `/readyz` returns 503 when `REQUIRE_REDIS=true` or `ENVIRONMENT=production` (`core/resilience/health.py:68`); otherwise Redis is only shown as degraded.
- Token revocation checks fail closed with 503 (`gateway/auth_refresh.py`, `assert_access_token_live`). SSE tokens cannot be issued or spent (`sse_token_set`, `sse_token_pop` raise 503).
- Per-user and per-org API rate limits: in production the request is refused with 503; in development a per-process counter is used (`core/api_rate_limit.py:1-9`).
- Login and registration limits: in production without Redis they deny the request (`core/rate_limiter.py`, `check_login_attempts`).
- Pause and cancel commands are written to a process-local dict even when Redis is down (`core/pipeline_state.py:145-148`). With several workers a command may not reach the worker that runs the pipeline. Not measured.
- The runbook previously said "no data loss, events replayed on reconnect". The code has no such replay that was found: not verified.

---

## 3. LLM Unavailability

### Detection
- Admin view of providers: `GET /system/components` (admin only, `gateway/routers/ops_status_router.py:33`).
- `/readyz` lists degraded components but model providers never make the API unready (`core/resilience/health.py:3-5`).

### How the router behaves
`core/model_router_providers.py:76-157` builds the chain from `PRIMARY_LLM` (default `bedrock`), then Anthropic and Gemini if configured, OpenRouter models if configured, then Ollama. A provider that fails hard is marked dead for a while and skipped. `OFFLINE_MODE=true` restricts the chain to Ollama.

### Recovery steps
1. Check the provider status page and your billing or quota.
2. Change the order: set `PRIMARY_LLM` (and the model variables in the chain description above) in `.env` and restart the service.
3. Per organisation: `PUT /settings/llm-config` (organisation LLM settings) or `POST /settings/llm/kill-switch`. There is no `POST /admin/settings` route.
4. While all providers are down, pipeline phases that call the LLM fail. The error text is whatever the provider returned.

---

## 4. Stuck Pipeline Run

The code has no stall monitor: `orchestrator/pipeline.py:126` says it was removed. Nothing logs a CRITICAL line for runs older than 30 minutes, and `/var/log/aetheros/app.log` is not written by the code. Service logs go to the journal (`SyslogIdentifier=aetheros` in `deploy/aetheros.service`).

### Detection
```bash
journalctl -u aetheros --since "1 hour ago" | tail -50      # host-specific unit name from deploy/aetheros.service
```
The table is `runs`, not `pipeline_runs`. `started_at` is a Unix timestamp (float) (`core/models.py:87-94`):
```bash
psql $DATABASE_URL -c "SELECT id, status, started_at, current_phase FROM runs WHERE status='running' AND started_at < EXTRACT(EPOCH FROM NOW() - INTERVAL '30 minutes');"
```

### Recovery steps
1. Take the `id` from the query.
2. Cancel through the API (`gateway/routers/run_decisions_router.py:84`). The cancel URL is under `/factory/runs`:
   ```bash
   curl -X POST http://localhost:8000/factory/runs/{run_id}/cancel \
     -H "Authorization: Bearer $TOKEN"
   ```
   An owner or admin can use the hard stop `POST /factory/runs/{run_id}/kill` (`run_decisions_router.py:103`).
3. If the API does not answer, set the status in the database:
   ```bash
   psql $DATABASE_URL -c "UPDATE runs SET status='cancelled', finished_at=EXTRACT(EPOCH FROM NOW()) WHERE id='{run_id}';"
   ```
   This only changes the row. It does not stop a worker that is still running the pipeline.
4. Look for leftover generated-app processes: `ps aux | grep "uvicorn\|run_app" | grep -v grep`, then stop them with `kill <PID>`.
5. A failed or cancelled run can be restarted from its checkpoint: `POST /factory/runs/{run_id}/restart` (409 for any other status).

---

## 5. OOM (Out of Memory)

Host-specific commands (not checked against the repository):
```bash
dmesg | grep -i "oom\|killed" | tail -10
free -h
ps aux --sort=-%mem | head -20
systemctl restart aetheros
```
If it keeps happening, lower `--workers 4` in `deploy/aetheros.service` (and the same value in `Dockerfile:51` for the container) and run `systemctl daemon-reload && systemctl restart aetheros`. Adding swap is an OS decision and is not covered here.

---

## 6. SSL Certificate Renewal

Host-specific. nginx config comes from `deploy/nginx.conf`; `deploy/deploy.sh --domain` fills the domain placeholders.
```bash
certbot renew --nginx --non-interactive
systemctl reload nginx
systemctl status certbot.timer
openssl s_client -connect <your-domain>:443 -servername <your-domain> 2>/dev/null | openssl x509 -noout -dates
```

---

## 7. Rollback Procedure

### Code
`deploy/deploy.sh` updates with `git pull --ff-only` (`deploy/deploy.sh:33`), so a rollback is a checkout of an earlier commit followed by a restart:
```bash
cd <install-dir>                  # for example the path in WorkingDirectory of deploy/aetheros.service
git log --oneline -10
git checkout <previous-commit>    # commit or stash local changes first
systemctl restart aetheros
```

### Database migration
```bash
alembic history --verbose | head -20
alembic downgrade -1
```
Whether every revision has a working `downgrade()` was not verified. `merge_r2_heads` itself is an empty merge.

### Check after rollback
```bash
curl -s http://localhost:8000/readyz
./scripts/smoke_test.sh http://localhost:8000      # needs AETHER_ADMIN_PASS or the password as the third argument
```

---

## 8. Backup & Restore

### Scripts in the repository
`scripts/backup_db.sh`, `scripts/db_backup.sh`, `scripts/restore_drill.py`, `deploy/aetheros-backup.service`, `deploy/aetheros-backup.timer`, `deploy/crontab.example`, `scripts/setup_backup_cron.sh`.

### `scripts/backup_db.sh`
- Needs `DATABASE_URL` (from the environment or `.env`). It refuses a SQLite URL (`scripts/backup_db.sh:27-36`).
- Writes `aetheros_<timestamp>.sql.gz` to `BACKUP_DIR` (default `/var/backups/aetheros`) and deletes older files after `RETAIN_DAYS` (default 7) (`scripts/backup_db.sh:8-11`).
- `deploy/crontab.example` runs it daily at 03:00 and logs to `/var/log/aetheros_backup.log`.

```bash
RETAIN_DAYS=14 ./scripts/backup_db.sh
ls -lht /var/backups/aetheros/ | head
```

### Restore (host-specific; the database and role names below are the compose defaults)
```bash
BACKUP_FILE=/var/backups/aetheros/aetheros_YYYYMMDD_HHMMSS.sql.gz
systemctl stop aetheros
psql -U postgres -c "DROP DATABASE IF EXISTS aether_os;"
psql -U postgres -c "CREATE DATABASE aether_os OWNER aether_user;"
gunzip -c "$BACKUP_FILE" | psql -U postgres -d aether_os
systemctl start aetheros
```
`scripts/restore_drill.py` exists for practising a restore; it was not read as part of this check.

---

## 9. SQLite to PostgreSQL

There is no script for this. `scripts/sqlite_to_pg.py` does not exist. `scripts/db_migrate.py` creates the schema on an empty PostgreSQL database but does not copy data. To move data from a development SQLite file you would have to write the copy yourself. The code has no tested path for it.

---

## 10. High Availability (reference design)

This section is a design sketch. The repository does not deploy or test a multi-node setup, and it contains no uptime target (`SECURITY.md` says the 99.9% claim was removed because nothing measures it). Treat the lists below as options to evaluate.

### 10.1 PostgreSQL
- `deploy/pgbouncer.ini` is a pgbouncer config in the repository: transaction pooling, listens on `127.0.0.1:6432`, `default_pool_size = 20`, `max_client_conn = 1000`, database `aetheros`.
- The SQLAlchemy engine uses `pool_pre_ping=True` (`core/db.py:83`).
- Replication and automatic failover (Patroni, repmgr) are not configured by anything in the repository.
- Check whether a node is a replica: `psql $DATABASE_URL -c "SELECT pg_is_in_recovery();"`.

### 10.2 Redis
The code reads one `REDIS_URL`. A grep for "sentinel" finds nothing in `core/`, `gateway/` or `orchestrator/`, so Redis Sentinel and Cluster URLs are not supported by the code. Use a single Redis (or a managed one behind one address).

### 10.3 Several API nodes behind nginx
The API holds the JWT state in Redis and the run data in PostgreSQL, so more than one node is possible in principle. Things that are per process: the pause and cancel dict (`core/pipeline_state.py:35`) and the model-router dead-provider table. How well several nodes work together was not measured.

```nginx
upstream aetheros {
    least_conn;
    server node1:8000 max_fails=3 fail_timeout=10s;
    server node2:8000 max_fails=3 fail_timeout=10s;
    keepalive 64;
}
server {
    listen 443 ssl http2;
    server_name <your-domain>;
    location / {
        proxy_pass         http://aetheros;
        proxy_http_version 1.1;
        proxy_set_header   Host $host;
        proxy_read_timeout 3600s;   # keep SSE connections alive
    }
}
```
The real nginx config of the project is `deploy/nginx.conf`.

### 10.4 Load balancer health check
Poll `GET /readyz`. It returns 200 when the instance can serve traffic and 503 when it cannot (`gateway/routers/health_router.py:53-59`). `GET /healthz` is liveness only. `GET /health` always returns `{"status": "ok", "timestamp", "service", "version"}` and checks nothing.

### 10.5 Rolling deploy
1. Run the migration once: `scripts/db_migrate.py` (Section 0). Only additive migrations are safe while old nodes still run.
2. Restart one node at a time and wait until `/readyz` returns 200:
   ```bash
   systemctl restart aetheros
   until curl -sf http://node1:8000/readyz > /dev/null; do sleep 2; done
   ```
3. Repeat for the next node. To roll back, see Section 7.

---

## 11. Velaris public app (careers, scheduling, interview participant, e-sign) - KAN-128

Own process, own host name, never on the dashboard host. Files: `deploy/nginx_velaris_public.conf`,
`deploy/velaris_public_proxy.conf`, `deploy/velaris-public.service`, compose service `velaris_public`
(profile `velaris`, loopback 8731 only), `scripts/velaris_public_smoke.sh`.

Owner steps (needs DNS + a certificate, nothing here does that for you):
1. DNS A/AAAA for the public host (for example `careers.<your-domain>`), then `certbot certonly --nginx -d <host>`.
2. Put the Velaris environment in `/etc/velaris/public.env` (mode 0600): `VELARIS_DATA`, `VELARIS_PUBLIC_CORS_ORIGINS`
   (the careers site origins), plus the Velaris secrets. The unit sets `VELARIS_PUBLIC_TRUST_PROXY=1` (exactly one proxy).
3. `bash deploy/velaris_public_setup.sh <host>` (installs site + unit, runs `nginx -t`, reloads).
4. `bash scripts/velaris_public_smoke.sh https://<host>`: the four prefixes reach the app, `/agents`, `/flows`, `/chat`,
   `/mail`, `/control`, `/hr`, `/metrics`, `/docs` and `/` answer 404.

What the proxy guarantees: path allowlist `/careers/ /schedule/ /interview/ /sign/`; Cookie, Authorization, X-Api-Key,
X-Org-Id and X-Velaris-* dropped; `X-Forwarded-For` replaced by the connection address (so per-IP limits see the real
client); 256 KiB body cap; per-IP rate and connection limits; `Referrer-Policy: no-referrer`; the access log keeps only
the first path segment (`/sign/***`) and never the query or Referer, so a link token is never logged. The nginx error log
is set to `crit`; a critical error line can still name the request, so do not ship that file to a third party.
Rollback: `systemctl disable --now velaris-public && rm /etc/nginx/sites-enabled/velaris-public && systemctl reload nginx`.
