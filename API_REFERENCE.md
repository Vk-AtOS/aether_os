# AetherOS — API Reference

**Base URL**: `https://<your-domain>/`  
**Authentication**: All protected endpoints require `Authorization: Bearer <access_token>` header.  
**Content-Type**: `application/json` for all request bodies.  
**SSE streams**: `Accept: text/event-stream`.

---

## Authentication

### POST /auth/register
Create a new user account and organisation.

**Auth required**: No

**Request body**:
```json
{
  "email": "user@example.com",
  "password": "minimum8chars",
  "full_name": "Alice Smith",
  "org_name": "Acme Corp"
}
```

**Response 201**:
```json
{
  "access_token": "eyJhbGci...",
  "refresh_token": "eyJhbGci...",
  "token_type": "bearer",
  "user": {
    "id": "usr_abc123",
    "email": "user@example.com",
    "full_name": "Alice Smith",
    "role": "owner",
    "org_id": "org_xyz789",
    "mfa_enabled": false
  }
}
```

---

### POST /auth/login
Exchange credentials for JWT access + refresh tokens.

**Auth required**: No

**Request body**:
```json
{
  "email": "user@example.com",
  "password": "yourpassword",
  "totp_code": "123456"
}
```
`totp_code` is required only when MFA is enabled on the account.

**Response 200**:
```json
{
  "access_token": "eyJhbGci...",
  "refresh_token": "eyJhbGci...",
  "token_type": "bearer",
  "user": {
    "id": "usr_abc123",
    "email": "user@example.com",
    "role": "admin",
    "org_id": "org_xyz789",
    "plan": "pro",
    "mfa_enabled": true
  }
}
```

**Error 401**: Invalid credentials or wrong TOTP code.  
**Error 429**: Rate limit exceeded (5 attempts / minute).

---

### POST /auth/refresh
Rotate refresh token and obtain a new access token.

**Auth required**: No (refresh token in body)

**Request body**:
```json
{
  "refresh_token": "eyJhbGci..."
}
```

**Response 200**: Same schema as `/auth/login` response.

**Error 401**: Token expired or revoked.

---

### POST /auth/logout
Revoke the current refresh token.

**Auth required**: Yes

**Request body**: None

**Response 200**:
```json
{ "message": "Logged out successfully" }
```

---

## Factory Pipeline

### POST /factory/start
Start a new pipeline run.

**Auth required**: Yes

**Request body**:
```json
{
  "raw_input": "Build a SaaS CRM with contact management, deal pipeline, and email integration",
  "project_name": "AcmeCRM",
  "domain": "saas",
  "client_id": "client_001",
  "is_change_request": false,
  "memory_context": null
}
```

`domain` options: `general`, `fintech`, `healthcare`, `saas`, `ecommerce`, `logistics`, `edtech`.

**Response 202**:
```json
{
  "run_id": "run_a1b2c3d4",
  "project_id": "proj_e5f6g7h8",
  "status": "queued",
  "created_at": "2026-05-19T10:00:00Z",
  "estimated_duration_minutes": 5
}
```

**Error 429**: Plan run limit reached.

---

### GET /factory/runs
List all pipeline runs for the authenticated organisation.

**Auth required**: Yes

**Query params**: `?status=running&limit=20&offset=0`

**Response 200**:
```json
{
  "runs": [
    {
      "run_id": "run_a1b2c3d4",
      "project_name": "AcmeCRM",
      "status": "completed",
      "current_phase": "p14_client_portal",
      "phases_completed": 20,
      "phases_total": 20,
      "created_at": "2026-05-19T10:00:00Z",
      "completed_at": "2026-05-19T10:06:30Z"
    }
  ],
  "total": 42,
  "limit": 20,
  "offset": 0
}
```

---

### GET /factory/runs/{run_id}
Get full detail of a pipeline run including per-phase output.

**Auth required**: Yes

**Response 200**:
```json
{
  "run_id": "run_a1b2c3d4",
  "project_id": "proj_e5f6g7h8",
  "project_name": "AcmeCRM",
  "domain": "saas",
  "status": "completed",
  "current_phase": "p14_client_portal",
  "phases": [
    {
      "name": "p01_intake_requirements",
      "status": "completed",
      "gate_passed": true,
      "gate_confidence": 0.9,
      "duration_seconds": 18,
      "output_path": "/var/aetheros/runs/run_a1b2c3d4/p01_intake_requirements"
    }
  ],
  "artifacts": [],
  "compliance_flags": ["GDPR", "SOC2"],
  "created_at": "2026-05-19T10:00:00Z"
}
```

---

### GET /factory/runs/{run_id}/stream
Stream real-time pipeline events over SSE.

**Auth required**: Yes (token via `?token=<sse_token>` obtained from `POST /factory/runs/{id}/sse-token`)

**Response**: `text/event-stream`
```
data: {"event": "phase_start", "phase": "p02_architecture", "ts": "2026-05-19T10:01:00Z"}

data: {"event": "phase_complete", "phase": "p02_architecture", "gate_passed": true, "ts": "2026-05-19T10:01:45Z"}

data: {"event": "run_complete", "run_id": "run_a1b2c3d4", "ts": "2026-05-19T10:06:30Z"}
```

---

### GET /factory/runs/{run_id}/artifacts
List all output artifacts for a run.

**Auth required**: Yes

**Response 200**:
```json
{
  "artifacts": [
    {
      "phase": "p04_backend",
      "file": "src/main.py",
      "size_bytes": 4821,
      "mime_type": "text/x-python"
    },
    {
      "phase": "p08_cicd_deployment",
      "file": "ci.yml",
      "size_bytes": 1240,
      "mime_type": "text/yaml"
    }
  ]
}
```

---

### POST /factory/runs/{run_id}/pause
Pause a running pipeline between phases.

**Auth required**: Yes (role: admin or owner)

**Response 200**: `{ "status": "paused" }`

---

### POST /factory/runs/{run_id}/resume
Resume a paused pipeline.

**Auth required**: Yes (role: admin or owner)

**Response 200**: `{ "status": "running" }`

---

### POST /factory/runs/{run_id}/cancel
Cancel a running pipeline. Cannot be undone.

**Auth required**: Yes (role: admin or owner)

**Response 200**: `{ "status": "cancelled" }`

---

### POST /factory/runs/{run_id}/rerun
Re-run the pipeline from a specific phase.

**Auth required**: Yes

**Request body**:
```json
{ "from_phase": "p06_review_security" }
```

**Response 202**: Same schema as `/factory/start` response.

---

## Full Development Environment (FDE)

### GET /factory/runs/{run_id}/file-content
Read a file from the generated project.

**Auth required**: Yes

**Query params**: `?path=src/main.py`

**Response 200**:
```json
{
  "path": "src/main.py",
  "content": "from fastapi import FastAPI\n...",
  "size_bytes": 4821,
  "last_modified": "2026-05-19T10:03:00Z"
}
```

---

### PATCH /factory/runs/{run_id}/file-content
Write file content (Monaco editor save).

**Auth required**: Yes

**Request body**:
```json
{
  "path": "src/main.py",
  "content": "from fastapi import FastAPI\n\napp = FastAPI()\n..."
}
```

**Response 200**: `{ "saved": true, "path": "src/main.py" }`

---

### POST /factory/runs/{run_id}/open-in-vscode
Open the generated project folder in the local VS Code installation.

**Auth required**: Yes

**Request body**: None

**Response 200**:
```json
{ "launched": true, "path": "/var/aetheros/runs/run_a1b2c3d4/project" }
```

**Error 500**: VS Code `code` CLI not found on PATH.

---

### GET /factory/runs/{run_id}/envvars
Read the `.env` file for the generated app.

**Auth required**: Yes

**Response 200**:
```json
{
  "vars": {
    "DATABASE_URL": "sqlite:///./app.db",
    "SECRET_KEY": "changeme",
    "DEBUG": "true"
  }
}
```

---

### PATCH /factory/runs/{run_id}/envvars
Update one or more env vars (written to `.env` on disk).

**Auth required**: Yes

**Request body**:
```json
{
  "vars": {
    "DATABASE_URL": "postgresql://user:pass@localhost/myapp",
    "DEBUG": "false"
  }
}
```

**Response 200**: `{ "updated": true }`

---

### POST /factory/runs/{run_id}/run-app
Start the generated application process.

**Auth required**: Yes

**Request body**: None

**Response 202**:
```json
{
  "pid": 12345,
  "port": 8001,
  "status": "starting",
  "stream_url": "/factory/runs/run_a1b2c3d4/run-app/stream"
}
```

---

### DELETE /factory/runs/{run_id}/run-app
Stop the running generated application process.

**Auth required**: Yes

**Response 200**: `{ "stopped": true }`

---

## Settings

### GET /settings/phases/config
Get per-phase configuration (enabled/disabled, LLM model override, timeout).

**Auth required**: Yes

**Response 200**:
```json
{
  "phases": {
    "p01_intake_requirements": { "enabled": true, "model": null, "timeout_seconds": 120 },
    "p06_review_security":     { "enabled": true, "model": "claude-sonnet-4-6", "timeout_seconds": 180 }
  }
}
```

---

### POST /settings/phases/{phase_name}/config
Update configuration for a specific phase.

**Auth required**: Yes (role: admin or owner)

**Request body**:
```json
{
  "enabled": true,
  "model": "gemini-2.5-flash",
  "timeout_seconds": 240
}
```

**Response 200**: Updated phase config object.

---

### GET /settings/llm-config
Get current LLM provider settings.

**Auth required**: Yes (role: admin or owner)

**Response 200**:
```json
{
  "primary_provider": "anthropic",
  "anthropic_key_set": true,
  "google_key_set": false,
  "openrouter_key_set": true,
  "active_model": "claude-sonnet-4-6"
}
```

---

### PUT /settings/llm-config
Update LLM provider keys and model selection.

**Auth required**: Yes (role: admin or owner)

**Request body**:
```json
{
  "provider": "anthropic",
  "api_key": "sk-ant-...",
  "model": "claude-sonnet-4-6"
}
```

**Response 200**: `{ "updated": true, "active_model": "claude-sonnet-4-6" }`

---

## Admin

### GET /admin/users
List all users in the organisation.

**Auth required**: Yes (role: admin or owner)

**Response 200**:
```json
{
  "users": [
    {
      "id": "usr_abc123",
      "email": "user@example.com",
      "full_name": "Alice Smith",
      "role": "admin",
      "is_active": true,
      "created_at": "2026-05-01T09:00:00Z",
      "last_login": "2026-05-19T08:30:00Z"
    }
  ],
  "total": 5
}
```

---

### POST /admin/users/{user_id}/role
Change a user's role.

**Auth required**: Yes (role: owner only)

**Request body**:
```json
{ "role": "member" }
```

Valid roles: `owner`, `admin`, `member`, `viewer`.

**Response 200**: `{ "updated": true, "role": "member" }`

---

### POST /admin/users/invite
Invite a new user to the organisation by email.

**Auth required**: Yes (role: admin or owner)

**Request body**:
```json
{
  "email": "newuser@example.com",
  "role": "member"
}
```

**Response 202**: `{ "invited": true, "email": "newuser@example.com" }`

---

### POST /admin/users/{user_id}/deactivate
Deactivate a user account (revokes all tokens).

**Auth required**: Yes (role: owner only)

**Response 200**: `{ "deactivated": true }`

---

### GET /admin/platform-health
Detailed platform health metrics (database, Redis, LLM providers, active runs).

**Auth required**: Yes (role: admin or owner)

**Response 200**:
```json
{
  "database": { "status": "ok", "latency_ms": 2 },
  "redis": { "status": "ok", "latency_ms": 1 },
  "llm_provider": { "status": "ok", "provider": "anthropic" },
  "active_runs": 3,
  "queued_runs": 1
}
```

---

## System

### GET /health
Basic liveness check. No auth required. Used by load balancers.

**Response 200**:
```json
{ "status": "ok", "version": "2.0.0" }
```

---

### GET /system/metrics
Detailed system metrics including CPU, memory, disk, and pipeline stats.

**Auth required**: No (intended for internal monitoring; restrict at nginx level in production)

**Response 200**:
```json
{
  "cpu_percent": 12.4,
  "memory": {
    "total_gb": 8.0,
    "used_gb": 3.2,
    "percent": 40.0
  },
  "disk": {
    "total_gb": 50.0,
    "used_gb": 12.1,
    "percent": 24.2
  },
  "pipeline": {
    "active_runs": 2,
    "completed_today": 14,
    "failed_today": 1
  },
  "uptime_seconds": 86400
}
```

---

## Error Responses

All errors follow this schema:

```json
{
  "detail": "Human-readable error description"
}
```

| HTTP Status | Meaning |
|-------------|---------|
| 400 | Bad request / validation error |
| 401 | Missing or invalid JWT |
| 403 | Insufficient role / plan gating |
| 404 | Resource not found |
| 422 | Pydantic validation error (body/params) |
| 429 | Rate limit exceeded |
| 500 | Internal server error (logged to Sentry) |
