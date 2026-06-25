# QUICKSTART GUIDE

Get DCSP running and see your first autonomous repair in under 10 minutes.

## 1. Prerequisites

- **Python 3.9+**
- **PostgreSQL 15+**
- **Redis** (for task queueing)
- **Ollama** (optional, for LLM-based repair)
- **Docker** (optional, for sandboxing)

## 2. Setup Environment

```bash
git clone https://github.com/Vk-AtOS/DSCP.git
cd DSCP
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file from the example:
```bash
cp .env.example .env
```

Ensure `DATABASE_URL` matches your local PostgreSQL setup.

## 3. Initialize Database

Run the migration script to create tables and seed demo data:
```bash
python scripts/migrate_db.py
python scripts/seed_demo_data.py
```

## 4. Start the Server

```bash
./scripts/start_demo.sh
```

The API will be available at `http://localhost:8000`.
The Dashboard will be at `http://localhost:8000/dashboard`.

**Login Credentials**:
- Username: `admin`
- Password: `dcsp2024`

## 5. Trigger a Test Repair

Use `curl` to simulate a CI failure:

```bash
curl -X POST "http://localhost:8000/webhook/ci-auto" \
  -H "Content-Type: application/json" \
  -d '{
    "repo_name": "acme/billing-service",
    "branch": "main",
    "ci_job_name": "pytest",
    "log_content": "AttributeError: NoneType object has no attribute get at processor.py:45"
  }'
```

## 6. Verify in Dashboard

1. Navigate to the **Dashboard** page.
2. You should see a new job entry for `acme/billing-service`.
3. Click **Details** to see the root cause analysis and the generated patch.
4. If configured with an LLM, DCSP will automatically propose a fix!
