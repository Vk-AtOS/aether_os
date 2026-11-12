"""Prime — executors: the only code that carries out an approved action.

An executor is called by prime/approvals.py, once, after the approval and hash
checks there. It reports in one of three ways:

  returns a dict          -> the action was carried out (the dict is the result)
  raises ExecutionFailed  -> the action was definitely NOT carried out
  raises anything else    -> unknown; the request is left "needs attention"

Executors never retry. A name that is not in the registry is refused.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

import httpx
from sqlalchemy import select

from aether_os.core.db import get_session_factory
from aether_os.core.encryption import decrypt
from aether_os.core.models import Run, Webhook
from aether_os.core.pipeline_state import get_control, set_control
# Reused, not re-implemented: the outbound address check and the HMAC signer of
# organisation webhooks. deliver_event()/send() themselves are not used because
# they retry, and an approved action must be attempted exactly once.
from aether_os.core.webhooks.delivery import _DELIVERY_TIMEOUT, _assert_safe_url, _delivery
from aether_os.prime.authz import Action

WEBHOOK_EVENT = "prime.execute"
SPEC_GATE_ACTION = "run.spec.approve"


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
            await asyncio.to_thread(_assert_safe_url, wh.url)  # resolves DNS: off the loop
        except ValueError as e:
            raise ExecutionFailed(f"address refused: {e}") from e
        try:
            async with httpx.AsyncClient(timeout=_DELIVERY_TIMEOUT) as client:
                resp = await client.post(wh.url, content=body, headers=headers)
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
        async with get_session_factory()() as session:
            found = (await session.execute(
                select(Run.id).where(Run.id == run_id, Run.org_id == ctx.org_id)
            )).scalar_one_or_none()
        if not found:
            raise ExecutionFailed("no such build in this organisation")
        control = await get_control(run_id)
        if control != "spec_review":
            raise ExecutionFailed(
                f"the build is not waiting at its specification review gate (state: {control})")
        await set_control(run_id, "spec_approved")
        return {"run_id": run_id, "gate": "spec_review", "control": "spec_approved"}


DEFAULT_EXECUTOR = DryRunExecutor.name
REGISTRY: Dict[str, Executor] = {
    e.name: e for e in (DryRunExecutor(), WebhookExecutor(), RunGateExecutor())
}


def get_executor(name: str) -> Optional[Executor]:
    """The registered executor, or None. Callers must refuse on None."""
    return REGISTRY.get(name)
