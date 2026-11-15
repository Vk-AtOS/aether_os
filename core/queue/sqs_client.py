"""
AetherOS SQS client — thin wrapper around boto3 for pipeline job queuing.

Only activated when SQS_QUEUE_URL is set in the environment. All imports are
deferred so the rest of the platform starts fine without boto3 installed.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

QUEUE_URL: str = os.environ.get("SQS_QUEUE_URL", "")


def _client():
    import boto3  # type: ignore
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    return boto3.client("sqs", region_name=region)


def is_enabled() -> bool:
    return bool(QUEUE_URL or os.environ.get("SQS_QUEUE_URL", ""))


def send_pipeline_job(run_id: str, params: Dict[str, Any]) -> bool:
    """
    Enqueue a pipeline run to SQS.
    params must be JSON-serialisable; it should contain all factory.run() kwargs.
    Returns True on success, False on error (caller should fall back to direct execution).
    """
    queue_url = QUEUE_URL or os.environ.get("SQS_QUEUE_URL", "")
    if not queue_url:
        return False
    try:
        body = json.dumps({"run_id": run_id, **params}, default=str)
        _client().send_message(
            QueueUrl=queue_url,
            MessageBody=body,
            MessageAttributes={
                "run_id": {"DataType": "String", "StringValue": run_id},
            },
        )
        logger.info("SQS: enqueued run %s", run_id)
        return True
    except Exception as exc:
        logger.error("SQS send_message failed for run %s: %s", run_id, exc)
        return False


def receive_jobs(max_messages: int = 1, wait_seconds: int = 20) -> List[Dict[str, Any]]:
    """
    Long-poll SQS for pipeline jobs.
    Returns list of dicts with keys: receipt_handle, run_id, params.
    """
    queue_url = QUEUE_URL or os.environ.get("SQS_QUEUE_URL", "")
    if not queue_url:
        return []
    try:
        response = _client().receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_seconds,
            MessageAttributeNames=["All"],
            AttributeNames=["ApproximateReceiveCount"],
            VisibilityTimeout=3600,  # 1 hour — matches pipeline timeout
        )
        messages = response.get("Messages", [])
        jobs = []
        for msg in messages:
            try:
                body = json.loads(msg["Body"])
                run_id = body.pop("run_id", None) or msg.get("MessageAttributes", {}).get("run_id", {}).get("StringValue", "")
                jobs.append({
                    "receipt_handle": msg["ReceiptHandle"],
                    "run_id": run_id,
                    "params": body,
                    "receive_count": int(msg.get("Attributes", {}).get("ApproximateReceiveCount", 1)),
                    "body": msg["Body"],
                })
            except Exception as parse_exc:
                logger.error("SQS message parse error: %s", parse_exc)
        return jobs
    except Exception as exc:
        logger.error("SQS receive_message failed: %s", exc)
        return []


def delete_job(receipt_handle: str) -> None:
    """Delete (ack) a processed message from the queue."""
    queue_url = QUEUE_URL or os.environ.get("SQS_QUEUE_URL", "")
    if not queue_url:
        return
    try:
        _client().delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
    except Exception as exc:
        logger.error("SQS delete_message failed: %s", exc)


def change_visibility(receipt_handle: str, visibility_timeout: int = 3600) -> None:
    """Extend the visibility timeout for a long-running job."""
    queue_url = QUEUE_URL or os.environ.get("SQS_QUEUE_URL", "")
    if not queue_url:
        return
    try:
        _client().change_message_visibility(
            QueueUrl=queue_url,
            ReceiptHandle=receipt_handle,
            VisibilityTimeout=visibility_timeout,
        )
    except Exception as exc:
        logger.warning("SQS change_visibility failed: %s", exc)


def send_to_dlq(body: str, reason: str) -> bool:
    """Park a poison message in SQS_DLQ_URL (if configured) so it can be inspected; True if parked."""
    dlq = os.environ.get("SQS_DLQ_URL", "")
    if not dlq:
        return False
    try:
        _client().send_message(
            QueueUrl=dlq, MessageBody=body,
            MessageAttributes={"reason": {"DataType": "String", "StringValue": reason[:200]}},
        )
        return True
    except Exception as exc:
        logger.error("SQS DLQ send failed: %s", exc)
        return False


def peek_dlq(limit: int = 10) -> List[Dict[str, Any]]:
    """Look at (not consume) up to `limit` (max 10) dead-lettered messages: run id and reason only, never the body.

    VisibilityTimeout=0 leaves them visible to the next reader. SQS cannot page a peek, so this is a window, not a listing.
    """
    dlq = os.environ.get("SQS_DLQ_URL", "")
    if not dlq:
        return []
    try:
        resp = _client().receive_message(
            QueueUrl=dlq, MaxNumberOfMessages=max(1, min(int(limit), 10)), WaitTimeSeconds=0, VisibilityTimeout=0,
            MessageAttributeNames=["All"], AttributeNames=["SentTimestamp", "ApproximateReceiveCount"])
    except Exception as exc:
        logger.error("SQS DLQ peek failed: %s", exc)
        return []
    items = []
    for msg in resp.get("Messages", []):
        try:
            run_id = json.loads(msg["Body"]).get("run_id", "")
        except (ValueError, AttributeError):
            run_id = ""
        attrs = msg.get("MessageAttributes", {})
        items.append({"message_id": msg["MessageId"], "run_id": run_id,
                      "reason": attrs.get("reason", {}).get("StringValue", ""),
                      "sent_at_ms": int(msg.get("Attributes", {}).get("SentTimestamp", 0)),
                      "receive_count": int(msg.get("Attributes", {}).get("ApproximateReceiveCount", 0))})
    return items


def dlq_depth() -> int:
    """Approximate number of dead-lettered messages (-1 when it cannot be read)."""
    dlq = os.environ.get("SQS_DLQ_URL", "")
    if not dlq:
        return 0
    try:
        attrs = _client().get_queue_attributes(QueueUrl=dlq, AttributeNames=["ApproximateNumberOfMessages"])
        return int(attrs["Attributes"]["ApproximateNumberOfMessages"])
    except Exception as exc:
        logger.error("SQS DLQ depth failed: %s", exc)
        return -1
