# API REFERENCE

Programmatic interaction with the DCSP platform.

## Authentication

Most `GET` endpoints require a valid `session_token` cookie.
Server-to-server endpoints (like Webhooks) use `X-Hub-Signature-256` or `X-API-Key`.

## Endpoints

### `POST /webhook/ci-auto`
Trigger an autonomous repair attempt.
- **Auth**: Optional HMAC Signature
- **Body**:
  ```json
  {
    "repo_name": "string",
    "branch": "string",
    "log_content": "string"
  }
  ```

### `GET /api/jobs`
List recent repair jobs.
- **Auth**: Required (Session)
- **Response**: List of Job objects

### `GET /api/jobs/{job_id}`
Retrieve full details for a specific job.
- **Auth**: Required (Session)

### `GET /api/intelligence/predictions`
Get ML-lite failure recurrence predictions.
- **Auth**: Required (Session)

### `GET /api/incidents`
List correlated failure incidents.
- **Auth**: Required (Session)

### `GET /api/security/audit`
Run a security configuration audit.
- **Auth**: Required (Session)

### `GET /api/notifications/status`
Check push notification configuration and logs.
- **Auth**: Required (Session)

### `GET /health`
Service health check (Database, Redis, Ollama).
- **Auth**: None

## Example cURL

**Get Health Status**:
```bash
curl http://localhost:8000/health
```

**Get Predictions**:
```bash
curl http://localhost:8000/api/intelligence/predictions \
  -H "Cookie: session_token=<your_token>"
```
