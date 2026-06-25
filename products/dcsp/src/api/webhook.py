"""
GitHub Actions CI event receiver webhook for DCSP.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from src.pipeline import run_repair, RepairResult
from src.database import get_db, SessionLocal
from src.models import FailureFingerprint, RepairJob
from src.api.state import add_job_to_history
from src.adapters import detect_adapter
from src.db.job_repo import save_job
from src.repo import REPO_MANAGER, GLOBAL_INDEXER
from src.security import (
    verify_github_signature,
    verify_gitlab_token,
    verify_jenkins_token,
    GLOBAL_SECRET_MANAGER,
    GLOBAL_RATE_LIMITER
)
from src.notifications import GLOBAL_NOTIFICATION_ROUTER, NotificationEvent

# Note: CallGraph still mocked or in-memory
_CALL_GRAPH = None  # This would be an instance of CallGraph

router = APIRouter()


def _save_job_bg(job_data: dict):
    """Background task to save job to DB, ensuring no crashes if DB is down."""
    try:
        session = SessionLocal()
        try:
            save_job(session, job_data)
        finally:
            session.close()
    except Exception as e:
        print(f"WARNING: Failed to save job to database in background: {e}")


def _notify_bg(event: NotificationEvent):
    """Background task to send notifications."""
    try:
        GLOBAL_NOTIFICATION_ROUTER.notify(event)
    except Exception as e:
        print(f"WARNING: Failed to send notifications in background: {e}")


class CIWebhookRequest(BaseModel):
    """Payload for GitHub CI job failure event."""

    repo_name: str
    branch: str
    ci_job_name: str
    log_content: str


class CISeedRequest(BaseModel):
    """Payload for seeding historical patch records."""

    error_type: str
    stack_trace_pattern: str
    failing_test: str
    target_module: str
    patch_diff: str
    success_rate: float


from src.db.audit_repo import save_audit_log

@router.post("/ci", response_model=RepairResult)
async def ci_webhook(request: Request, payload: CIWebhookRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Handle CI job failure events and attempt repair.
    """
    client_ip = request.client.host if request.client else "unknown"
    save_audit_log(db, "webhook_received", "system", repo_name=payload.repo_name, details=f"CI System: github_actions, Job: {payload.ci_job_name}", ip_address=client_ip)

    # 1. Signature Verification
    body = await request.body()
    ci_system = "github_actions" # Default for this endpoint
    secret = GLOBAL_SECRET_MANAGER.get_webhook_secret(ci_system)
    
    if secret:
        sig = request.headers.get("X-Hub-Signature-256", "")
        if not verify_github_signature(body, sig, secret):
            raise HTTPException(status_code=401, detail="Invalid GitHub signature")
    else:
        print(f"WARNING: No webhook secret configured for {ci_system}, skipping signature verification")

    # 2. Rate Limiting
    client_ip = request.client.host if request.client else "unknown"
    if not GLOBAL_RATE_LIMITER.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    try:
        # Load historical records from PostgreSQL
        records = db.query(FailureFingerprint).all()
        historical_records = [
            {
                "fingerprint_hash": r.fingerprint_hash,
                "error_type": r.error_type,
                "stack_trace_pattern": r.stack_trace_pattern,
                "failing_test": r.failing_test,
                "target_module": r.target_module,
                "patch_diff": r.patch_diff,
                "success_rate": r.success_rate,
            }
            for r in records
        ]
        
        # Repository source context (new in Batch 10)
        repo_root = "."
        indexer = GLOBAL_INDEXER
        try:
            repo_url = f"https://github.com/{payload.repo_name}.git"
            repo_root = REPO_MANAGER.clone_or_pull(repo_url)
            indexer.index_repository(repo_root)
        except Exception as e:
            print(f"WARNING: Failed to index repository {payload.repo_name}: {e}")
            # Continue with empty context rather than failing
            indexer.clear()

        # Run the repair orchestrator
        result = run_repair(
            log_content=payload.log_content,
            root_dir=repo_root,
            historical_records=historical_records,
            ast_index=indexer,
            call_graph=_CALL_GRAPH
        )
        
        job_data = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "repo_name": payload.repo_name if hasattr(payload, "repo_name") else payload.get("repo_name", "unknown"),
            "branch": payload.branch if hasattr(payload, "branch") else payload.get("branch", "unknown"),
            "ci_system": ci_system,
            "detected_language": result.detected_language,
            "success": result.success,
            "confidence": result.confidence,
            "escalated": result.escalated,
            "explanation": result.explanation,
            "patch_diff": result.patch_diff,
            "slm_generated": result.slm_generated,
            "violations": result.violations,
            "source": result.source,
            "fingerprint": result.fingerprint,
            "sandbox_result": getattr(result, "sandbox_result", None)
        }

        # Update in-memory history
        add_job_to_history(job_data)

        # Broadcast update to WebSockets
        import asyncio
        import threading
        from src.api.websocket_manager import MANAGER
        
        def _broadcast(job_data):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    MANAGER.broadcast_job_update(
                        "new_job", job_data))
            finally:
                loop.close()
        
        threading.Thread(
            target=_broadcast,
            args=(job_data,),
            daemon=True
        ).start()

        # Save to database in background
        background_tasks.add_task(_save_job_bg, job_data)

        # Build notification event and send in background
        status = "success" if result.success else ("escalated" if result.escalated else "failed")
        
        # Feed into predictor
        try:
            from src.intelligence.predictor import PREDICTOR
            if result.error_type:
                PREDICTOR.record_failure(
                    error_type=result.error_type,
                    language=result.detected_language or "unknown",
                    fingerprint=result.fingerprint or "",
                    repo_name=job_data.get("repo_name", ""),
                    was_resolved=result.success
                )
        except Exception as _pred_err:
            import logging
            logging.getLogger("src.api.webhook").warning(f"Predictor feed failed: {_pred_err}")

        notif_event = NotificationEvent(
            job_id=job_data["id"],
            repo_name=payload.repo_name,
            branch=payload.branch,
            status=status,
            confidence=result.confidence,
            explanation=result.explanation,
            patch_diff=result.patch_diff or "",
            source=result.source,
            fingerprint=result.fingerprint,
            timestamp=job_data["timestamp"]
        )
        background_tasks.add_task(_notify_bg, notif_event)

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ci/auto")
async def ci_webhook_auto(request: Request, payload: dict, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Automatically detect CI system from payload and run repair.
    """
    client_ip = request.client.host if request.client else "unknown"
    save_audit_log(db, "webhook_auto_received", "system", details="Auto-detecting CI adapter", ip_address=client_ip)

    adapter = detect_adapter(payload)
    if not adapter:
        raise HTTPException(status_code=400, detail="unrecognized CI payload")

    # 1. Signature Verification
    body = await request.body()
    ci_system = adapter.name
    secret = GLOBAL_SECRET_MANAGER.get_webhook_secret(ci_system)

    if secret:
        if ci_system == "github_actions":
            sig = request.headers.get("X-Hub-Signature-256", "")
            if not verify_github_signature(body, sig, secret):
                raise HTTPException(status_code=401, detail="Invalid GitHub signature")
        elif ci_system == "gitlab_ci":
            token = request.headers.get("X-Gitlab-Token", "")
            if not verify_gitlab_token(token, secret):
                raise HTTPException(status_code=401, detail="Invalid GitLab token")
        elif ci_system == "jenkins":
            token = request.query_params.get("token", "")
            if not verify_jenkins_token(token, secret):
                raise HTTPException(status_code=401, detail="Invalid Jenkins token")
    else:
        print(f"WARNING: No webhook secret configured for {ci_system}, skipping signature verification")

    # 2. Rate Limiting
    client_ip = request.client.host if request.client else "unknown"
    if not GLOBAL_RATE_LIMITER.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    event = adapter.parse(payload)
    if not event:
        raise HTTPException(status_code=400, detail="failed to parse CI payload")

    try:
        # Load historical records from PostgreSQL
        records = db.query(FailureFingerprint).all()
        historical_records = [
            {
                "fingerprint_hash": r.fingerprint_hash,
                "error_type": r.error_type,
                "stack_trace_pattern": r.stack_trace_pattern,
                "failing_test": r.failing_test,
                "target_module": r.target_module,
                "patch_diff": r.patch_diff,
                "success_rate": r.success_rate,
            }
            for r in records
        ]

        # Repository source context (new in Batch 10)
        repo_root = "."
        indexer = GLOBAL_INDEXER
        try:
            if adapter.name == "gitlab_ci":
                repo_url = f"https://gitlab.com/{event.repo_name}.git"
            else:
                # Default to GitHub for others
                repo_url = f"https://github.com/{event.repo_name}.git"

            repo_root = REPO_MANAGER.clone_or_pull(repo_url, event.commit_sha)
            indexer.index_repository(repo_root)
        except Exception as e:
            print(f"WARNING: Failed to index repository {event.repo_name}: {e}")
            indexer.clear()

        # Run the repair orchestrator
        result = run_repair(
            log_content=event.log_output,
            root_dir=repo_root,
            historical_records=historical_records,
            ast_index=indexer,
            call_graph=_CALL_GRAPH
        )

        job_data = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat(),
            "repo_name": event.repo_name,
            "branch": event.branch,
            "commit_sha": event.commit_sha,
            "ci_system": adapter.name,
            "detected_language": result.detected_language,
            "success": result.success,
            "confidence": result.confidence,
            "escalated": result.escalated,
            "explanation": result.explanation,
            "patch_diff": result.patch_diff,
            "slm_generated": result.slm_generated,
            "violations": result.violations,
            "source": result.source,
            "fingerprint": result.fingerprint,
            "sandbox_result": getattr(result, "sandbox_result", None)
        }

        # Update in-memory history
        add_job_to_history(job_data)

        # Broadcast update to WebSockets
        import asyncio
        import threading
        from src.api.websocket_manager import MANAGER
        
        def _broadcast(job_data):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    MANAGER.broadcast_job_update(
                        "new_job", job_data))
            finally:
                loop.close()
        
        threading.Thread(
            target=_broadcast,
            args=(job_data,),
            daemon=True
        ).start()

        # Save to database in background
        background_tasks.add_task(_save_job_bg, job_data)

        # Build notification event and send in background
        status = "success" if result.success else ("escalated" if result.escalated else "failed")
        
        # Feed into predictor
        try:
            from src.intelligence.predictor import PREDICTOR
            if result.error_type:
                PREDICTOR.record_failure(
                    error_type=result.error_type,
                    language=result.detected_language or "unknown",
                    fingerprint=result.fingerprint or "",
                    repo_name=job_data.get("repo_name", ""),
                    was_resolved=result.success
                )
        except Exception as _pred_err:
            import logging
            logging.getLogger("src.api.webhook").warning(f"Predictor feed failed: {_pred_err}")

        notif_event = NotificationEvent(
            job_id=job_data["id"],
            repo_name=event.repo_name,
            branch=event.branch,
            status=status,
            confidence=result.confidence,
            explanation=result.explanation,
            patch_diff=result.patch_diff or "",
            source=result.source,
            fingerprint=result.fingerprint,
            timestamp=job_data["timestamp"]
        )
        background_tasks.add_task(_notify_bg, notif_event)

        return {
            "ci_system": adapter.name,
            "success": result.success,
            "confidence": result.confidence,
            "explanation": result.explanation,
            "patch_diff": result.patch_diff,
            "escalated": result.escalated,
            "source": result.source,
            "fingerprint": result.fingerprint
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/github")
async def github_app_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Receive GitHub App webhook events (push, check_run, installation, ping).
    Signature is verified with HMAC-SHA256 when GITHUB_WEBHOOK_SECRET is set.
    """
    payload_bytes = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    from src.github_app import verify_webhook_signature
    if not verify_webhook_signature(payload_bytes, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        import json as _json
        payload = _json.loads(payload_bytes)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = request.headers.get("X-GitHub-Event", "")

    from src.github_webhook_handler import (
        handle_push_event,
        handle_check_run_event,
        handle_installation_webhook_event,
    )

    if event_type == "push":
        result = await handle_push_event(payload, db)
    elif event_type == "check_run":
        result = await handle_check_run_event(payload, db)
    elif event_type == "installation":
        result = await handle_installation_webhook_event(payload, db)
    elif event_type == "ping":
        result = {"status": "ok", "message": "DCSP GitHub App webhook connected"}
    else:
        result = {"status": "ignored", "event": event_type}

    return result


@router.post("/seed")
async def seed_historical_record(payload: CISeedRequest, db: Session = Depends(get_db)):
    """
    Seed a historical patch record into the PostgreSQL database.
    """
    # Compute fingerprint_hash using the same logic as src/patch_reuse/fingerprint.py
    canonical_payload = "\n".join([
        payload.error_type,
        payload.stack_trace_pattern,
        payload.failing_test,
        payload.target_module,
    ])
    fingerprint_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

    # Create model instance
    record = FailureFingerprint(
        error_type=payload.error_type,
        stack_trace_pattern=payload.stack_trace_pattern,
        failing_test=payload.failing_test,
        target_module=payload.target_module,
        patch_diff=payload.patch_diff,
        success_rate=payload.success_rate,
        fingerprint_hash=fingerprint_hash,
    )

    # Save to database
    try:
        db.add(record)
        db.commit()
        return {"seeded": True, "fingerprint_hash": fingerprint_hash}
    except Exception as e:
        db.rollback()
        # Handle duplicates or other errors
        if "unique constraint" in str(e).lower():
            return {"seeded": False, "reason": "Fingerprint already exists", "fingerprint_hash": fingerprint_hash}
        raise HTTPException(status_code=500, detail=str(e))
