# AetherOS Operational Runbook

## Table of Contents
1. [Database Failure](#1-database-failure)
2. [Redis Outage](#2-redis-outage)
3. [LLM Unavailability](#3-llm-unavailability)
4. [Stuck Pipeline Run](#4-stuck-pipeline-run)
5. [OOM (Out of Memory)](#5-oom-out-of-memory)
6. [SSL Certificate Renewal](#6-ssl-certificate-renewal)
7. [Rollback Procedure](#7-rollback-procedure)
8. [Backup & Restore](#8-backup--restore)
9. [SQLite → PostgreSQL Migration](#9-sqlite--postgresql-migration)
10. [High Availability Architecture](#10-high-availability-architecture)

---

## 1. Database Failure

### Detection
```bash
systemctl status postgresql
tail -50 /var/log/postgresql/postgresql-*.log
curl -s http://localhost:8000/health | python3 -m json.tool
```

### Recovery Steps
1. Check if Postgres process is running: `ps aux | grep postgres`
2. Attempt restart: `systemctl restart postgresql`
3. Check for disk full: `df -h /var/lib/postgresql`
4. Check for corrupt data: `sudo -u postgres pg_dumpall --check`
5. If unrecoverable, restore from backup (see Section 8)

### Impact While Down
- All API endpoints returning 500
- Pipeline runs cannot start or update state
- SSE streams will error

---

## 2. Redis Outage

### Detection
```bash
redis-cli -a "$REDIS_PASSWORD" ping
systemctl status redis
```

### Recovery Steps
1. Restart Redis: `systemctl restart redis`
2. Verify: `redis-cli -a "$REDIS_PASSWORD" ping` → should return `PONG`
3. Check memory: `redis-cli -a "$REDIS_PASSWORD" info memory`

### Impact While Down
- SSE live log events buffered locally (no live updates in UI)
- Pipeline pause/cancel commands queued locally
- Rate limiting falls back to in-process counters
- No data loss — pipeline continues running, events replayed on reconnect

---

## 3. LLM Unavailability

### Detection
```bash
curl -H "Authorization: Bearer $ANTHROPIC_API_KEY" \
  https://api.anthropic.com/v1/models
```

### Per-Provider Degradation
| Provider Down | Affected Features |
|---|---|
| Anthropic | All LLM code generation, council review, spec generation |
| Ollama | SLM self-healing repair (falls back to Anthropic) |
| OpenAI | Any GPT-based model routing |

### Recovery Steps
1. Check Anthropic status: https://status.anthropic.com
2. If quota exceeded: check billing at console.anthropic.com
3. Switch model in admin settings: `POST /admin/settings` with `default_model`
4. For temporary outage: pipeline runs will fail at LLM phases with clear error messages

---

## 4. Stuck Pipeline Run

### Detection
```bash
# Runs stuck for >30 min are logged as CRITICAL
grep "STALL\|stuck" /var/log/aetheros/app.log | tail -20

# Check active runs in DB
psql $DATABASE_URL -c "SELECT id, status, started_at, current_phase FROM pipeline_runs WHERE status='running' AND started_at < NOW() - INTERVAL '30 minutes';"
```

### Recovery Steps
1. Get the stuck run_id from the query above
2. Kill the run via API:
   ```bash
   curl -X POST http://localhost:8000/runs/{run_id}/cancel \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```
3. If API unresponsive, kill directly in DB:
   ```bash
   psql $DATABASE_URL -c "UPDATE pipeline_runs SET status='cancelled', completed_at=NOW() WHERE id='{run_id}';"
   ```
4. Clean up any leftover processes:
   ```bash
   # Find orphaned uvicorn processes for generated apps
   ps aux | grep "uvicorn\|run_app" | grep -v grep
   kill -9 <PID>
   ```

---

## 5. OOM (Out of Memory)

### Detection
```bash
dmesg | grep -i "oom\|killed" | tail -10
free -h
cat /proc/meminfo | grep -E "MemTotal|MemAvailable|Cached"
```

### Recovery Steps
1. Identify memory hog: `ps aux --sort=-%mem | head -20`
2. Restart AetherOS: `systemctl restart aetheros`
3. If recurring, increase swap:
   ```bash
   fallocate -l 4G /swapfile
   chmod 600 /swapfile
   mkswap /swapfile
   swapon /swapfile
   echo '/swapfile none swap sw 0 0' >> /etc/fstab
   ```
4. For persistent OOM, reduce worker count in aetheros.service:
   Change `--workers 4` to `--workers 2`

---

## 6. SSL Certificate Renewal

### Manual Renewal
```bash
certbot renew --nginx --non-interactive
systemctl reload nginx
```

### Verify Certificate
```bash
openssl s_client -connect yourdomain.com:443 -servername yourdomain.com 2>/dev/null | openssl x509 -noout -dates
```

### Auto-renewal (should already be set up by certbot)
```bash
systemctl status certbot.timer
# Should show active (running)
```

---

## 7. Rollback Procedure

### Quick Rollback (last deploy)
```bash
# On VPS
cd /home/aether_os
git log --oneline -10  # Find the previous good commit
git stash  # Save any local changes
git checkout <previous-commit-hash>
systemctl restart aetheros
```

### Rollback Database Migration
```bash
cd /home/aether_os
# List applied migrations
alembic history --verbose | head -20
# Roll back one revision
alembic downgrade -1
# Or roll back to specific revision
alembic downgrade <revision_id>
```

### Smoke Test After Rollback
```bash
curl -s http://localhost:8000/health | python3 -m json.tool
curl -s http://localhost:8000/api/v1/status
```

---

## 8. Backup & Restore

### Manual Backup
```bash
/home/aether_os/deploy/scripts/backup.sh
# Backups stored in /var/backups/aetheros/
ls -lht /var/backups/aetheros/ | head -10
```

### Restore from Backup
```bash
BACKUP_FILE=/var/backups/aetheros/aether_os_YYYYMMDD_HHMMSS.dump

# Stop the app
systemctl stop aetheros

# Drop and recreate DB
psql -U postgres -c "DROP DATABASE IF EXISTS aether_os;"
psql -U postgres -c "CREATE DATABASE aether_os OWNER aether_user;"

# Restore
pg_restore -U postgres -d aether_os "$BACKUP_FILE"

# Restart
systemctl start aetheros
```

---

## 9. SQLite → PostgreSQL Migration

> **Note:** The production VPS already runs PostgreSQL. This section is for migrating a development SQLite instance.

### Steps
1. Export from SQLite:
   ```bash
   python3 -c "
   import sqlite3, json
   conn = sqlite3.connect('aether_os.db')
   conn.row_factory = sqlite3.Row
   data = {}
   for table in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall():
       rows = conn.execute(f'SELECT * FROM {table[0]}').fetchall()
       data[table[0]] = [dict(r) for r in rows]
   json.dump(data, open('sqlite_export.json', 'w'))
   "
   ```
2. Run Alembic migrations on PostgreSQL: `alembic upgrade head`
3. Import data using a script (available in `scripts/sqlite_to_pg.py` if present)
4. Verify row counts match
5. Update `DATABASE_URL` in `.env` to point to PostgreSQL
6. Zero-downtime: use a maintenance window of ~5 minutes, run migrations first, then switch `DATABASE_URL`, then restart the service

---

## 10. High Availability Architecture

This section describes the reference HA topology for running AetherOS in a production environment where the 99.9% SLA (see SECURITY.md) must be met.

### 10.1 PostgreSQL: Primary + Streaming Replica

**Topology**
- One primary PostgreSQL node (writes + reads)
- One or more hot-standby streaming replicas (read-only; automatic failover via Patroni or repmgr)
- pgBouncer runs on every app server as a local connection pooler (transaction-mode, pool_size=20 per AetherOS worker)

**Key configuration snippets**
```ini
# postgresql.conf (primary)
wal_level = replica
max_wal_senders = 5
wal_keep_size = 1GB
synchronous_commit = on   # or 'remote_apply' for zero-data-loss

# pgbouncer.ini (on each app server)
[databases]
aether_os = host=127.0.0.1 port=5432 dbname=aether_os
[pgbouncer]
pool_mode = transaction
max_client_conn = 200
default_pool_size = 20
server_idle_timeout = 60
```

**Failover**
1. Patroni (or repmgr) detects primary failure (heartbeat timeout, default 30 s)
2. Replica is promoted: `patronictl failover aether_os --master <old-primary> --candidate <replica>`
3. pgBouncer reconnects automatically; in-flight transactions are retried by SQLAlchemy (pool_pre_ping=True)
4. Update `DATABASE_URL` in `.env` if the IP changes, then reload AetherOS without restart: `kill -HUP <uvicorn-pid>`

**Health check**
```bash
psql $DATABASE_URL -c "SELECT pg_is_in_recovery(), now();"
# Primary returns f | <timestamp>; replica returns t | <timestamp>
```

---

### 10.2 Redis: Sentinel or Cluster

AetherOS uses Redis for SSE event fan-out, pipeline pause/cancel signals, and sliding-window rate limiting.

**Redis Sentinel (recommended for 1-3 node setups)**
```
Sentinel 1 ─┐
Sentinel 2 ─┼─ monitors ──► Redis Primary ──► Redis Replica
Sentinel 3 ─┘
```

- Minimum quorum: 2 of 3 sentinels must agree before failover
- AetherOS connects via sentinel URL: `redis+sentinel://sentinel1:26379,sentinel2:26379/mymaster/0`
- Set `REDIS_URL` in `.env` to the sentinel URL; the `redis-py` client handles discovery automatically

**Redis Cluster (for horizontal scale)**
- 6 nodes minimum: 3 primary shards + 3 replicas
- AetherOS's pub/sub keys are prefixed by `org_id`; cluster hash-tags ensure related keys land on the same shard: `{org:<org_id>}:sse:<run_id>`

**Failover timeline**
- Sentinel detects primary failure after `down-after-milliseconds` (default 5 000 ms)
- Promotion completes within ~10 s; SSE clients reconnect automatically (EventSource retry)
- Rate-limit counters reset to zero on failover — this is acceptable (brief over-allowance)

---

### 10.3 AetherOS API Servers Behind nginx Upstream

Run two or more AetherOS processes (separate VMs or containers) behind an nginx upstream.

```nginx
upstream aetheros {
    least_conn;
    server 10.0.0.1:8000 max_fails=3 fail_timeout=10s;
    server 10.0.0.2:8000 max_fails=3 fail_timeout=10s;
    keepalive 64;
}

server {
    listen 443 ssl http2;
    server_name aetheros.ai;

    location / {
        proxy_pass         http://aetheros;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host $host;
        proxy_read_timeout 3600s;   # keep SSE connections alive
    }

    location /health {
        proxy_pass http://aetheros/health;
        access_log off;             # suppress noisy health-check logs
    }
}
```

**Session affinity** — AetherOS is stateless (JWT auth, no server-side sessions); `least_conn` load balancing is sufficient. SSE streams are handled by the server that accepted the initial HTTP connection; nginx upstream keepalive ensures the same backend is reused for the stream lifetime.

---

### 10.4 Load Balancer Health Check

The nginx (or any external load balancer / cloud health check) should poll:

```
GET /health
```

**Expected response (HTTP 200)**
```json
{
  "status": "ok",
  "db": "ok",
  "redis": "ok",
  "version": "0.1.x"
}
```

- If `db` or `redis` is `"error"`, nginx `max_fails` will remove the node from the upstream pool.
- If the HTTP status is non-200, the node is immediately marked down.

Configure the load-balancer interval to **10 s**, failure threshold **3**, success threshold **2**.

---

### 10.5 Zero-Downtime Rolling Deployment

Use this procedure whenever deploying a new AetherOS build to a multi-node cluster.

**Prerequisites**
- All pending Alembic migrations are backward-compatible (additive only — no column drops or renames that would break the old code)
- New build artifact is available on all nodes (e.g. `git pull` or pre-pulled Docker image)

**Step-by-step**

1. **Run database migrations once** (from any node, before touching the app):
   ```bash
   cd /home/aether_os && alembic upgrade head
   ```

2. **Rolling restart — one node at a time:**
   ```bash
   # On node 1:
   systemctl restart aetheros
   # Wait for health check to pass (nginx re-adds node):
   until curl -sf http://node1:8000/health | grep -q '"status":"ok"'; do sleep 2; done
   echo "Node 1 healthy"

   # Repeat for node 2, 3, …
   ```

3. **Verify all nodes are healthy:**
   ```bash
   for node in node1 node2; do
     curl -sf http://${node}:8000/health | python3 -m json.tool
   done
   ```

4. **Rollback** (if a node fails to come up): follow Section 7. Alembic migrations that have not yet been applied to other nodes can be reversed with `alembic downgrade -1` before restarting the old binary.

---

### 10.6 Reference Architecture (Text Description)

```
Internet
    │
    ▼
[Cloudflare / CDN]  ← TLS termination, DDoS mitigation
    │
    ▼
[nginx (2 VMs, active-active)]
    │  least_conn, health-check /health
    ├──► AetherOS API Server 1  (uvicorn, 4 workers)
    └──► AetherOS API Server 2  (uvicorn, 4 workers)
              │                           │
              └──────────┬────────────────┘
                         │
              ┌──────────▼──────────┐
              │   pgBouncer (local) │  (on each app server)
              └──────────┬──────────┘
                         │
              ┌──────────▼──────────┐
              │  PostgreSQL Primary │ ──streaming replication──► PostgreSQL Replica
              └─────────────────────┘
                         │
              ┌──────────▼──────────┐
              │  Redis Primary      │ ──replication──► Redis Replica
              │  (Sentinel cluster) │
              └─────────────────────┘
```

**Component sizing for 99.9% uptime target**

| Component | Minimum for HA | Recommended |
|---|---|---|
| AetherOS API servers | 2 | 3 |
| PostgreSQL nodes | 2 (1 primary + 1 replica) | 3 (Patroni) |
| Redis nodes | 3 (Sentinel quorum) | 6 (Cluster) |
| nginx load balancers | 2 (active-active) | 2 + Keepalived VIP |
