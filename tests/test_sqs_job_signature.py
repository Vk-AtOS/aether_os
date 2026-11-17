"""KAN-69 SC-08: with SQS_JOB_HMAC_KEY set a job body is signed, and a worker refuses an unsigned or altered one."""
import json

import pytest

import aether_os.core.queue.sqs_client as sq


class FakeSqs:
    def __init__(self):
        self.sent, self.deleted, self.inbox = [], [], []

    def send_message(self, **kw):
        self.sent.append(kw)

    def receive_message(self, **kw):
        return {"Messages": self.inbox}

    def delete_message(self, **kw):
        self.deleted.append(kw["ReceiptHandle"])


@pytest.fixture
def sqs(monkeypatch):
    fake = FakeSqs()
    monkeypatch.setattr(sq, "_client", lambda: fake)
    monkeypatch.setattr(sq, "QUEUE_URL", "https://q")
    monkeypatch.setenv("SQS_DLQ_URL", "https://dlq")
    monkeypatch.setenv("SQS_JOB_HMAC_KEY", "k" * 32)
    return fake


def _msg(body, handle):
    return {"Body": body, "ReceiptHandle": handle, "Attributes": {"ApproximateReceiveCount": "1"}}


def test_signed_job_round_trips_and_a_forged_or_altered_one_is_parked(sqs):
    assert sq.send_pipeline_job("r1", {"org_id": "o1", "raw_input": "x", "n": 1.5})
    signed = sqs.sent[0]["MessageBody"]
    altered = json.loads(signed) | {"org_id": "victim-org"}
    unsigned = json.dumps({"run_id": "r2", "org_id": "o1"})
    sqs.inbox = [_msg(signed, "good"), _msg(json.dumps(altered), "alt"), _msg(unsigned, "uns")]
    jobs = sq.receive_jobs(10, 0)
    assert [j["run_id"] for j in jobs] == ["r1"] and jobs[0]["params"]["org_id"] == "o1"
    assert sorted(sqs.deleted) == ["alt", "uns"]                      # refused, parked in the DLQ, then removed
    assert len([m for m in sqs.sent if m["QueueUrl"] == "https://dlq"]) == 2


def test_without_a_key_unsigned_jobs_are_still_accepted(sqs, monkeypatch):
    monkeypatch.delenv("SQS_JOB_HMAC_KEY")
    sqs.inbox = [_msg(json.dumps({"run_id": "r3"}), "h")]
    assert [j["run_id"] for j in sq.receive_jobs(1, 0)] == ["r3"]
