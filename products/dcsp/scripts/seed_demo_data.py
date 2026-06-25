"""
Seed demo data for DCSP dashboard.
Populates both in-memory state and PostgreSQL database.

Re-running this script is safe: tenants are get-or-created (no duplicates),
and jobs use random UUIDs so each run adds a fresh set of 20 demo jobs.

H-fixes applied:
  H1: Incidents are created for escalated and failed jobs.
  H4: slm_generated=False for all seeded records — only the live pipeline sets it True.
  H7: get_or_create pattern for tenants prevents 125+ duplicate rows on re-seed.
"""

import json
import logging
import os
import sys
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to sys.path to allow imports from src
root_dir = Path(__file__).parent.parent
sys.path.append(str(root_dir))

# Load .env before importing src modules so DATABASE_URL and AWS_* are set.
from dotenv import load_dotenv
load_dotenv(root_dir / ".env")

from src.api.state import add_job_to_history
from src.db.job_repo import save_job
from src.db.tenant_repo import get_tenant_by_slug, create_tenant
from src.db.incident_repo import get_or_create_incident
from src.database import SessionLocal
from src.feedback import fingerprint

logger = logging.getLogger(__name__)

REPOS = ["acme/billing-service", "acme/auth-service", "acme/payment-api", "acme/frontend-ui"]
LANGUAGES = ["python", "javascript", "java"]
CI_SYSTEMS = ["github_actions", "jenkins", "gitlab_ci"]

PYTHON_LOG = """Traceback (most recent call last):
  File "src/auth/service.py", line 45, in authenticate
    if user.password == password:
AttributeError: 'NoneType' object has no attribute 'password'"""

JS_LOG = """TypeError: Cannot read property 'password' of null
    at authenticate (src/auth/service.js:45:18)
    at Object.<anonymous> (tests/auth.test.js:10:5)"""

JAVA_LOG = """java.lang.NullPointerException: Cannot invoke "User.getPassword()" because "user" is null
    at com.acme.auth.Service.authenticate(Service.java:45)
    at com.acme.auth.ServiceTest.testAuthenticate(ServiceTest.java:10)"""

SUCCESS_DIFF = """--- a/src/auth/service.py
+++ b/src/auth/service.py
@@ -45,7 +45,7 @@
 def authenticate(user, password):
-    if user.password == password:
+    if check_password_hash(user.password, password):
     return True"""


def _get_or_create_tenant(session, name: str, plan: str = "free"):
    """
    Return existing tenant by slug, or create it.
    Prevents duplicate tenants on repeated seeder runs (H7).
    """
    from src.db.tenant_repo import slugify
    slug = slugify(name)
    existing = get_tenant_by_slug(session, slug)
    if existing:
        return existing
    return create_tenant(session, name, plan)


def generate_fake_job(status_type, index=0):
    now = datetime.utcnow()
    lang = random.choice(LANGUAGES)
    repo = random.choice(REPOS)

    if status_type == "success":
        success = True
        escalated = False
        confidence = random.uniform(0.85, 0.99)
        explanation = f"Fixed null pointer dereference in authenticate() at {repo} line 45"
        patch_diff = SUCCESS_DIFF
        # H4: seeded jobs must NOT set slm_generated=True.  Only the live pipeline
        # sets slm_generated=True after an actual SLM inference call.
        slm_generated = False
        violations = []
        source = "slm" if index < 8 else "memory"
    elif status_type == "escalated":
        success = False
        escalated = True
        confidence = random.uniform(0.3, 0.6)
        explanation = (
            f"Automated repair failed: insufficient context for ZeroDivisionError "
            f"in {repo.split('/')[-1]}_processor.py"
        )
        patch_diff = None
        slm_generated = False
        violations = []
        source = "slm"
    else:  # failed
        success = False
        escalated = False
        confidence = random.uniform(0.1, 0.4)
        explanation = "Patch failed DSEE boundary verification"
        patch_diff = None
        slm_generated = False
        violations = ["Patch modifies files outside src/ boundary"]
        source = "slm"

    if lang == "python":
        raw_log = PYTHON_LOG
    elif lang == "javascript":
        raw_log = JS_LOG
    else:
        raw_log = JAVA_LOG

    timestamp = (
        now
        - timedelta(
            days=random.randint(0, 7),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
        )
    )

    return {
        "id": str(uuid.uuid4()),
        "timestamp": timestamp.isoformat(),
        "repo_name": repo,
        "branch": random.choice(["main", "develop", "feature/login"]),
        "commit_sha": os.urandom(20).hex(),
        "ci_system": random.choice(CI_SYSTEMS),
        "detected_language": lang,
        "success": success,
        "confidence": confidence,
        "escalated": escalated,
        "explanation": explanation,
        "patch_diff": patch_diff,
        "slm_generated": slm_generated,
        "approved": None,
        "violations": violations,
        "raw_log": raw_log,
        "source": source,
        "fingerprint": fingerprint(raw_log),
        "approved_pr_url": None,
    }


def main():
    print("Generating 20 realistic demo jobs...")

    jobs = []
    # 12 success
    for i in range(12):
        jobs.append(generate_fake_job("success", i))
    # 5 escalated
    for i in range(5):
        jobs.append(generate_fake_job("escalated", i))
    # 3 failed
    for i in range(3):
        jobs.append(generate_fake_job("failed", i))

    # Set PR URLs for 3 approved jobs
    pr_urls = [
        "https://github.com/acme/billing-service/pull/42",
        "https://github.com/acme/auth-service/pull/17",
        "https://github.com/acme/api-gateway/pull/8",
    ]

    # Find 3 successful jobs to "approve" and give PRs
    success_jobs = [j for j in jobs if j["success"]]
    for i in range(min(3, len(success_jobs))):
        success_jobs[i]["approved"] = True
        success_jobs[i]["approved_pr_url"] = pr_urls[i]

    # Sort by timestamp to add them in order
    jobs.sort(key=lambda x: x["timestamp"])

    session = SessionLocal()
    try:
        # H7: get_or_create the default tenant — prevents duplicate rows on re-seed.
        tenant = _get_or_create_tenant(session, "Default", "enterprise")
        tenant_id = tenant.id
        print(f"Tenant: {tenant.name} (slug={tenant.slug}, id={tenant_id})")

        incident_count = 0
        for job_data in jobs:
            job_data["tenant_id"] = tenant_id

            # Seed in-memory
            add_job_to_history(job_data)

            # Seed Database (strip raw_log which is not in the RepairJob model)
            db_data = {k: v for k, v in job_data.items() if k != "raw_log"}
            save_job(session, db_data)

            # H1: create Incident records for escalated and failed jobs.
            # The seeder previously only created RepairJob rows, so the Incidents
            # page was always empty after a fresh seed.
            if job_data["escalated"] or not job_data["success"]:
                try:
                    fp_val = job_data.get("fingerprint", "unknown")
                    lang = job_data.get("detected_language", "unknown")
                    repo = job_data.get("repo_name", "unknown")
                    error_type = "ZeroDivisionError" if job_data["escalated"] else "PatchValidationError"
                    incident = get_or_create_incident(
                        session,
                        fingerprint=fp_val,
                        error_type=error_type,
                        language=lang,
                        repo_name=repo,
                    )
                    # Escalated jobs → mark the incident as escalated too
                    if job_data["escalated"] and incident.status == "active":
                        incident.status = "escalated"
                        session.commit()
                    incident_count += 1
                except Exception as inc_err:
                    logger.warning("Could not create incident for job %s: %s",
                                   job_data["id"], inc_err)

        print(
            f"Successfully seeded {len(jobs)} jobs "
            f"(12 success, 5 escalated, 3 failed) and {incident_count} incident records."
        )
    except Exception as e:
        print(f"Error during seeding: {e}")
        raise
    finally:
        session.close()


def seed_demo_data() -> None:
    """
    Callable from app startup. Idempotent: checks if demo data already exists
    before seeding to avoid flooding the DB on every restart.
    """
    try:
        from src.database import SessionLocal
        from src.models import RepairJob
        session = SessionLocal()
        try:
            count = session.query(RepairJob).count()
            if count > 0:
                return  # Already seeded — skip
        finally:
            session.close()
        main()
    except Exception as e:
        logger.warning("seed_demo_data failed: %s", e)


if __name__ == "__main__":
    main()
