"""Prime — executors: the only code that carries out an approved action.

An executor is called by prime/approvals.py, once, after the approval and hash
checks there. It reports in one of three ways:

  returns a dict          -> the action was carried out (the dict is the result)
  raises ExecutionFailed  -> the action was definitely NOT carried out
  raises anything else    -> unknown; the request is left "needs attention"

Executors never retry. A name that is not in the registry is refused.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

import httpx
from sqlalchemy import select

from aether_os.core.db import get_session_factory
from aether_os.core.encryption import decrypt
from aether_os.core.models import Webhook
# Reused, not re-implemented: the outbound address check and the HMAC signer of
# organisation webhooks. deliver_event()/send() themselves are not used because
# they retry, and an approved action must be attempted exactly once.
from aether_os.core.security.safe_http import UnsafeURL, safe_request
from aether_os.core.spec_approval import decide_spec
from aether_os.core.velaris.client import VelarisClient, VelarisUnavailable
from aether_os.core.velaris.identity import identity_for
from aether_os.core.webhooks.delivery import _DELIVERY_TIMEOUT, _delivery
from aether_os.prime.authz import Action

WEBHOOK_EVENT = "prime.execute"
SPEC_GATE_ACTION = "run.spec.approve"
VELARIS_FLOW_ACTION = "velaris.flow.call"
# Tests replace this to fake Velaris; production leaves it None (real HTTP).
velaris_transport: Optional[httpx.AsyncBaseTransport] = None
_RUN_ID = re.compile(r"[A-Za-z0-9]{1,64}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ARGS_SHOWN = 2000


class ExecutionFailed(Exception):
    """The action was not carried out, and it is certain that it was not."""


@dataclass(frozen=True)
class ExecutionContext:
    request_id: str
    org_id: str
    action: Action
    idempotency_key: str
    approved_by: str


class Executor(Protocol):
    name: str

    async def describe(self, ctx: ExecutionContext) -> str:
        """One sentence a person reads before approving: exactly what will happen."""

    async def execute(self, ctx: ExecutionContext) -> Dict[str, Any]: ...


class DryRunExecutor:
    """Carries out nothing. The safe default, and what the tests use."""
    name = "dry_run"

    async def describe(self, ctx: ExecutionContext) -> str:
        return "Dry run: the decision is recorded and nothing is carried out."

    async def execute(self, ctx: ExecutionContext) -> Dict[str, Any]:
        return {"dry_run": True, "action_type": ctx.action.type}


class WebhookExecutor:
    """POSTs the approved action, signed, to one of the organisation's own webhooks.

    Allow-list: the webhook (params.webhook_id) must belong to the organisation, be
    active, and list the event "prime.execute" by name; a catch-all webhook does not count.
    """
    name = "webhook"

    async def _webhook(self, ctx: ExecutionContext) -> Webhook:
        webhook_id = ctx.action.params.get("webhook_id")
        if not isinstance(webhook_id, str) or not webhook_id:
            raise ExecutionFailed("params.webhook_id is required")
        async with get_session_factory()() as session:
            wh = (await session.execute(select(Webhook).where(
                Webhook.id == webhook_id, Webhook.org_id == ctx.org_id,
                Webhook.is_active == True,  # noqa: E712
            ))).scalar_one_or_none()
        if wh is None or WEBHOOK_EVENT not in (wh.events or []):
            raise ExecutionFailed(
                f"no active webhook of this organisation is subscribed to '{WEBHOOK_EVENT}' "
                "under that id")
        return wh

    async def describe(self, ctx: ExecutionContext) -> str:
        try:
            wh = await self._webhook(ctx)
        except ExecutionFailed as e:
            return f"Would fail: {e}."
        return (f"Send one signed '{WEBHOOK_EVENT}' message with this action to {wh.url}. "
                "What happens next is up to that system.")

    async def execute(self, ctx: ExecutionContext) -> Dict[str, Any]:
        wh = await self._webhook(ctx)
        try:
            secret = decrypt(wh.secret or "")
        except ValueError as e:
            raise ExecutionFailed("the webhook has no usable signing secret; re-create it") from e
        body = json.dumps({
            "id": ctx.idempotency_key, "event": WEBHOOK_EVENT, "ts": time.time(),
            "payload": {"request_id": ctx.request_id, "approved_by": ctx.approved_by,
                        **ctx.action.model_dump(mode="json")},
        }, separators=(",", ":")).encode()
        headers = {
            "Content-Type": "application/json",
            "X-AetherOS-Event": WEBHOOK_EVENT,
            "X-AetherOS-Delivery": ctx.idempotency_key,
            "Idempotency-Key": ctx.idempotency_key,
            "X-AetherOS-Signature-256": f"sha256={_delivery._sign(body, secret)}",
        }
        try:
            resp = await safe_request("POST", wh.url, content=body, headers=headers,
                                      timeout=_DELIVERY_TIMEOUT)
        except UnsafeURL as e:
            raise ExecutionFailed(f"address refused: {e}") from e
        except httpx.ConnectError as e:
            raise ExecutionFailed("could not connect to the endpoint") from e
        # Any other transport error (timeout, dropped connection) propagates: the
        # endpoint may have acted, so the outcome is unknown.
        if 200 <= resp.status_code < 300:
            return {"status_code": resp.status_code, "url": wh.url}
        if 400 <= resp.status_code < 500:
            raise ExecutionFailed(f"the endpoint refused the message (HTTP {resp.status_code})")
        raise RuntimeError(f"endpoint answered HTTP {resp.status_code}; outcome unknown")


class RunGateExecutor:
    """Releases an AetherOS build waiting at its specification review gate.

    Same effect as POST /factory/runs/{run_id}/approve-spec: sets the run's control
    flag to "spec_approved", which orchestrator/spec_review_gate.py is polling for.
    """
    name = "aetheros.run_gate"

    def _run_id(self, ctx: ExecutionContext) -> str:
        run_id = ctx.action.params.get("run_id")
        if ctx.action.type != SPEC_GATE_ACTION or not isinstance(run_id, str) or not run_id:
            raise ExecutionFailed(f"only '{SPEC_GATE_ACTION}' with params.run_id is supported")
        return run_id

    async def describe(self, ctx: ExecutionContext) -> str:
        try:
            run_id = self._run_id(ctx)
        except ExecutionFailed as e:
            return f"Would fail: {e}."
        return (f"Approve the specification of build {run_id} so it continues past its "
                "review gate.")

    async def execute(self, ctx: ExecutionContext) -> Dict[str, Any]:
        run_id = self._run_id(ctx)
        outcome = await decide_spec(run_id, ctx.org_id, actor=f"prime:{ctx.request_id}", via="prime",
                                    metadata={"approved_by": ctx.approved_by})
        if outcome != "approved":
            raise ExecutionFailed(f"the build could not be approved here ({outcome})")
        return {"run_id": run_id, "gate": "spec_review", "control": "spec_approved"}


def velaris_call_hash(tool: str, args: Dict[str, Any]) -> str:
    """Velaris's own call hash (velaris.intel.flow.call_hash), recomputed here so the arguments an
    approver is shown are provably the ones the hash, and so request_hash, covers."""
    return hashlib.sha256(json.dumps([tool, args], sort_keys=True, default=str).encode()).hexdigest()


class VelarisFlowExecutor:
    """Nudges a Velaris run whose waiting step was approved here.

    Velaris asked for this approval (velaris/core/prime.py PrimeGate) and keeps the step until
    it has read, from Prime, that the request is approved AND this executor finished with
    "succeeded". So this executor carries no authority: it GETs /flows/{run_id} signed as the
    person the run is for, which makes Velaris look. While it runs, Prime's own state is still
    "running", so Velaris cannot yet see "succeeded" and the run is normally still
    waiting_approval here; it moves on the next time anyone reads the run (the dashboard's
    pending list does). Success therefore means: the run exists for this person, waits on
    exactly the approved call (or has already moved past it), and Velaris answered.
    """
    name = "velaris.flow"

    def _params(self, ctx: ExecutionContext) -> Dict[str, Any]:
        p = ctx.action.params
        run_id, call_hash, tool, args = (p.get(k) for k in ("run_id", "call_hash", "tool", "args"))
        if ctx.action.type != VELARIS_FLOW_ACTION:
            raise ExecutionFailed(f"only '{VELARIS_FLOW_ACTION}' is supported")
        if not (isinstance(run_id, str) and _RUN_ID.match(run_id) and isinstance(call_hash, str)
                and _HASH.match(call_hash) and isinstance(tool, str) and tool and isinstance(args, dict)):
            raise ExecutionFailed("params need run_id, call_hash, tool and args")
        if velaris_call_hash(tool, args) != call_hash:
            raise ExecutionFailed("call_hash does not match the tool and arguments")
        return p

    async def describe(self, ctx: ExecutionContext) -> str:
        try:
            p = self._params(ctx)
        except ExecutionFailed as e:
            return f"Would fail: {e}."
        args = json.dumps(p["args"], sort_keys=True, default=str)
        if len(args) > _ARGS_SHOWN:
            args = f"{args[:_ARGS_SHOWN]}... ({len(args)} characters; the full arguments are in the request)"
        return (f"Run {p['tool']} with {args} in Velaris on behalf of {ctx.action.on_behalf_of}. "
                "Velaris runs it only after it has read this approval from Prime.")

    async def execute(self, ctx: ExecutionContext) -> Dict[str, Any]:
        p = self._params(ctx)
        who = await identity_for(ctx.org_id, ctx.action.on_behalf_of)
        if who is None:
            raise ExecutionFailed("the person this run is for is not an active member of the organisation")
        try:
            client = VelarisClient.from_env(transport=velaris_transport)
        except VelarisUnavailable as e:
            raise ExecutionFailed(f"Velaris is not set up: {e}") from None
        try:
            status, run = await client.request(who, "GET", f"/flows/{p['run_id']}")
        except VelarisUnavailable as e:
            raise RuntimeError(f"Velaris could not be asked: {e}") from None  # unknown: needs attention
        if status == 409:
            raise RuntimeError("Velaris was busy with this run")
        if status != 200 or not isinstance(run, dict):
            raise ExecutionFailed(f"Velaris would not show this run to that person (HTTP {status})")
        state = run.get("status")
        if state == "waiting_approval":
            pending = run.get("pending") if isinstance(run.get("pending"), dict) else {}
            if pending.get("call_hash") != p["call_hash"]:
                raise ExecutionFailed("the run waits on a different call than the one approved")
            return {"run_id": p["run_id"], "run_status": state, "advanced": False}
        if state in ("done", "stopped"):
            return {"run_id": p["run_id"], "run_status": state, "advanced": True}
        raise RuntimeError(f"Velaris reported run state {str(state)[:40]!r}")  # unknown: needs attention


DEFAULT_EXECUTOR = DryRunExecutor.name
REGISTRY: Dict[str, Executor] = {
    e.name: e for e in (DryRunExecutor(), WebhookExecutor(), RunGateExecutor(), VelarisFlowExecutor())
}


def get_executor(name: str) -> Optional[Executor]:
    """The registered executor, or None. Callers must refuse on None."""
    return REGISTRY.get(name)
