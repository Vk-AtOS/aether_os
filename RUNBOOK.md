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
