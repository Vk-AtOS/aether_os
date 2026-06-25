# DCSP — Dynamic Code Self-healing Pipeline

![Tests Passing](https://img.shields.io/badge/Tests-459%20Passing-success)
![Python Version](https://img.shields.io/badge/Python-3.9-blue)
![Framework](https://img.shields.io/badge/Framework-FastAPI-green)
![Docker](https://img.shields.io/badge/Docker-Ready-blue)

DCSP is an autonomous self-healing pipeline designed to detect, analyze, and repair CI/CD failures in real-time. By leveraging Large Language Models (LLMs) and specialized static analysis, DCSP localizes root causes, generates targeted patches, validates them in isolated Docker sandboxes, and submits Pull Requests automatically. It features multi-tenancy, real-time WebSocket updates, predictive intelligence, and a federated pattern-sharing network.

## 🚀 Key Features

- **Autonomous Repair**: End-to-end flow from CI failure to verified Pull Request.
- **Log Analysis & Localization**: Uses DFLE (Dynamic Failure Localization Engine) to pinpoint bugs.
- **Multi-Tenant Architecture**: Isolate data and jobs across different organizations or teams.
- **Docker Sandboxing**: Validates patches in isolated containers before they reach your codebase.
- **Predictive Intelligence**: ML-lite recurrence scoring and severity prediction for failure patterns.
- **Real-time Dashboard**: Live updates via WebSockets for job status, analytics, and incidents.
- **Federation Network**: Securely share anonymized repair patterns with other DCSP instances.
- **VS Code Extension**: Trigger repairs and view status directly from the developer's editor.
- **Compliance & Audit**: Full audit trail of every automated action and manual approval.

## 🏗 Architecture

```text
                                     +----------------------+
                                     |   Federation Registry|
                                     +----------^-----------+
                                                | (Anonymized)
[CI System] --(Webhook)--> [API] --(Queue)--> [Repair Agent] --(PR)--> [GitHub/GitLab]
                            |                   |
                    [PostgreSQL/Redis]   [Docker Sandbox]
                            |                   |
                    [Dashboard UI] <--(WS)-- [Intelligence Engine]
```

## ⏱ Quick Start

1. **Clone and Install**:
   ```bash
   git clone https://github.com/Vk-AtOS/DSCP.git && cd DSCP
   python -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure**:
   ```bash
   cp .env.example .env
   # Edit .env with your DATABASE_URL and OLLAMA_HOST
   ```

3. **Initialize Database**:
   ```bash
   python scripts/migrate_db.py
   python scripts/seed_demo_data.py
   ```

4. **Start the Platform**:
   ```bash
   ./scripts/start_demo.sh
   ```

5. **Access Dashboard**:
   Open `http://localhost:8000/dashboard` (Login: `admin` / `dcsp2024`).

## 🔗 CI Integration

Add the DCSP webhook to your CI system:
- **Endpoint**: `http://<your-dcsp-host>/webhook/ci-auto`
- **Content-Type**: `application/json`
- **Secret**: Configure `WEBHOOK_SECRET` in DCSP and provide it as the HMAC key.

## 📊 Dashboard Overview

- **Dashboard**: Real-time feed of all repair jobs.
- **Analytics**: ROI tracking, success rates, and hours saved.
- **Incidents**: Correlated groups of failures across different repositories.
- **Intelligence**: Recurrence predictions and severity scoring.
- **Security**: Automated audit of system configuration.
- **Admin**: Tenant and plan management.
- **API Keys**: Manage programmatic access tokens.

## 🔮 Predictive Failure Engine

DCSP now includes an intelligence layer that predicts pipeline failures before they happen.

- **Baseline Learning**: Automatically builds statistical baselines (avg, std_dev) for every pipeline stage.
- **Risk Assessment**: Uses Z-score analysis to identify stages that are running unusually slow or fast, predicting potential timeouts or resource exhaustion.
- **API Endpoints**:
    - `GET /predict/stage/{name}`: Get risk for a current stage duration.
    - `GET /predict/pipeline/{job_id}`: Overall health prediction for a running job.
    - `GET /predict/baselines`: View all learned stage statistics.

## 🔗 Aether2 Integration

The `Aether2Bridge` allows Aether2 users to leverage DCSP for monitoring and self-healing.

```python
from src.integrations.aether2_bridge import Aether2Bridge

bridge = Aether2Bridge()
bridge.connect("http://dcsp-api:8000", "your-api-key")
bridge.register_pipeline("prod-deploy-1", ["build", "test", "deploy"])
```

## 📦 Per-Product Configuration

You can now generate tailored DCSP configurations for different products and domains.

```bash
python3 scripts/clone_for_product.py --product hexaware --domain hr
```

Configurations are stored in `config/products/` and include customized stage expectations and self-healing policies.

## ⚙️ Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://...` |
| `REDIS_URL` | Redis connection for queueing | `redis://localhost:6379/0` |
| `SECRET_KEY` | Key for session encryption | `change-me` |
| `WEBHOOK_SECRET`| HMAC key for CI webhooks | `""` |
| `SANDBOX_ENABLED`| Enable Docker patch validation| `false` |
| `OLLAMA_HOST` | URL for local LLM service | `http://localhost:11434`|

## 🔌 VS Code Extension

Install the extension from `extensions/vscode`. It allows you to:
- Right-click a file -> `DCSP: Repair Current File`.
- View real-time status in the status bar.
- Open the dashboard directly from the editor.

## 🐳 Deployment

### Docker Compose
```bash
docker-compose up -d
```

### Kubernetes
```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/
```

## 🔒 Security Checklist

- [ ] Change the default `ADMIN_PASSWORD`.
- [ ] Set a strong `SECRET_KEY`.
- [ ] Enable `SANDBOX_ENABLED` for patch verification.
- [ ] Use HTTPS (`BASE_URL`) in production.
- [ ] Rotate API keys regularly via the Admin panel.

## 🤝 Contributing

We welcome contributions! Please see `CONTRIBUTING.md` for our engineering standards and PR process. Ensure all 459+ tests pass before submitting.

## 📄 License

This project is licensed under the MIT License. See `LICENSE` for details.
