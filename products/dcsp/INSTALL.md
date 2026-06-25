# INSTALL - DCSP Enterprise On-Premise Setup

DCSP (Dynamic Code Self-healing Pipeline) is a fully offline, on-premise CI repair tool designed for secure, private infrastructure.

## Prerequisites

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| RAM       | 16GB    | 32GB        |
| CPU       | 4-Core  | 8-Core      |
| Disk      | 20GB    | 100GB       |
| OS        | Linux / macOS / WSL2 | Ubuntu 22.04 LTS |
| Software  | Docker, Docker Compose | Latest Stable |

## Quick Start

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/your-org/dcsp.git
    cd dcsp
    ```

2.  **Start the stack**:
    ```bash
    docker-compose up -d
    ```

3.  **Open the dashboard**:
    Navigate to `http://localhost:8000/dashboard` and log in.

## Configuration Reference

Configure the system via environment variables in `docker-compose.yml` or a `.env` file:

- `DATABASE_URL`: PostgreSQL connection string.
- `REDIS_URL`: Redis connection string for caching.
- `OLLAMA_URL`: URL of the Ollama service (default: `http://ollama:11434`).
- `OLLAMA_MODEL`: The SLM to use (default: `deepseek-coder:6.7b`).
- `SECRET_KEY`: Used for session security.
- `LOG_LEVEL`: Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`).

## How It Works

1.  **CI Ingestion**: Your CI system sends a failure event via webhook.
2.  **Standardization**: The CI Adapter parses the payload into a common format.
3.  **Localization**: DCSP identifies the root cause using AST indexing and stack trace analysis.
4.  **Repair**: The local SLM (Ollama + DeepSeek) generates a potential fix.
5.  **Verification**: DSEE runs tiered tests and impact analysis to validate the patch.
6.  **Delivery**: The verified patch appears on your dashboard for approval.

## CI Integration Examples

### GitHub Actions
Add this step to your workflow:
```yaml
- name: Notify DCSP
  if: failure()
  run: |
    curl -X POST http://dcsp-server:8000/webhook/ci/auto \
      -H "Content-Type: application/json" \
      -d @$GITHUB_EVENT_PATH
```

### Jenkins
Using the HTTP Request plugin:
```groovy
httpRequest httpMode: 'POST', 
            url: "http://dcsp-server:8000/webhook/ci/auto",
            contentType: 'APPLICATION_JSON',
            requestBody: '{"build": {"full_url": "${env.BUILD_URL}", "log": "${getLog()}"}}'
```

### GitLab CI
Add to your `.gitlab-ci.yml`:
```yaml
after_script:
  - >
    if [ "$CI_JOB_STATUS" == "failed" ]; then
      curl -X POST http://dcsp-server:8000/webhook/ci/auto \
        -H "Content-Type: application/json" \
        -d "{\"object_kind\": \"pipeline\", \"project\": {\"path_with_namespace\": \"$CI_PROJECT_PATH\"}, \"object_attributes\": {\"ref\": \"$CI_COMMIT_REF_NAME\", \"sha\": \"$CI_COMMIT_SHA\"}}"
    fi
```

## Upgrading

To upgrade DCSP to the latest version:
```bash
docker-compose pull
docker-compose up -d
```

## Troubleshooting

- **Ollama not starting**: Ensure you have at least 16GB of RAM. Check logs with `docker-compose logs ollama`.
- **DB connection failed**: Ensure the `postgres` container is healthy. Verify `DATABASE_URL` credentials.
- **Webhook 422 error**: This usually means the payload format is unrecognized. Check if a compatible CI Adapter exists.

## Demo Credentials

- **Admin**: `admin` / `dcsp2024`
- **Demo**: `demo` / `demo123`
