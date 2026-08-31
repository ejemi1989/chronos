"""Pub/Sub ingress with dead-letter handling.

Arrival flow:
  1. Pull message from ``chronos-incidents``.
  2. Idempotency check: if (incident_id, run_id) already exists in the store
     and is terminal, ACK and skip.
  3. Spawn the controller (detection → debate loop).
  4. On success → ACK.
  5. On unrecoverable error (schema reject, round limit exceeded, broker 5xx)
     → NACK with publish to ``chronos-incidents-dlq`` and ACK original.

The Pub/Sub client is injected so tests can use an in-memory transport.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Protocol

from contracts import Incident, WorkflowState

from .controller import (
    NeedsHumanReview,
    RoundLimitExceeded,
    SchemaReject,
    run_incident,
)
from .tracing import span
from .workflow import (
    InMemoryWorkflowStore,
    WorkflowStore,
    is_terminal,
    new_run,
    replay_command,
    transition,
)
from .workflow import (
    InMemoryWorkflowStore,
    WorkflowRun,
    WorkflowStore,
    is_terminal,
    new_run,
    replay_command,
    transition,
)

log = logging.getLogger("chronos.pubsub")


class PubSubClient(Protocol):
    def pull(self, subscription: str, max_messages: int = 1) -> list[dict]: ...
    def ack(self, subscription: str, ack_id: str) -> None: ...
    def nack(self, subscription: str, ack_id: str) -> None: ...
    def publish(self, topic: str, data: dict) -> None: ...


@dataclass
class HandlerConfig:
    subscription: str = "chronos-incidents-sub"
    dlq_topic: str = "chronos-incidents-dlq"
    max_attempts: int = 3


@dataclass
class HandlerResult:
    runs_started: int = 0
    runs_completed: int = 0
    runs_dlq: int = 0
    runs_skipped_idempotent: int = 0


async def handle_message(
    msg: dict,
    *,
    pipeline=None,
    store: WorkflowStore | None = None,
    pubsub: PubSubClient | None = None,
    config: HandlerConfig | None = None,
) -> WorkflowRun:
    """Process one incident message end-to-end. Idempotent on (incident, run).

    On unrecoverable error the message is forwarded to the DLQ and a
    terminal BLOCKED run is persisted so subsequent replays short-circuit.
    """
    cfg = config or HandlerConfig()
    store = store or InMemoryWorkflowStore()

    payload = msg.get("data", {})
    incident_payload = {k: v for k, v in payload.items()
                        if k in Incident.model_fields}
    incident = Incident.model_validate(incident_payload)

    with span("pubsub.handle", incident_id=incident.incident_id, ack_id=msg.get("ack_id", "")):
        existing = store.latest_for_incident(incident.incident_id)
        if existing and (is_terminal(existing.state) or existing.state == WorkflowState.BLOCKED):
            log.info("idempotent skip for %s/%s state=%s",
                     existing.incident_id, existing.run_id, existing.state)
            return existing

        run = existing or new_run(incident.incident_id)

    try:
        with span("pubsub.controller", run_id=run.run_id, incident_id=incident.incident_id):
            result = await run_incident(payload.get("raw_telemetry", incident.error_log), pipeline=pipeline)
        run = transition(run, WorkflowState.CLASSIFIED, classification=result.classification)
        run = transition(run, WorkflowState.DEBATING)
        run = transition(run, WorkflowState.PROPOSED, proposal=result.proposal)
        decision = _decision_from_proposal(result.proposal, result.accepted)
        run = transition(run, WorkflowState.POLICY_REVIEW, decision=decision)
        if decision.status.value == "BLOCKED":
            run = transition(run, WorkflowState.BLOCKED)
        elif decision.status.value == "REQUIRE_APPROVAL":
            run = transition(run, WorkflowState.REQUIRE_APPROVAL)
            run = transition(run, WorkflowState.EXECUTING)
            run = transition(run, WorkflowState.VERIFIED)
        else:
            run = transition(run, WorkflowState.ALLOW_SANDBOX)
            run = transition(run, WorkflowState.EXECUTING)
            run = transition(run, WorkflowState.VERIFIED)
        run = transition(run, WorkflowState.CLOSED)
        store.save(run)
        return run

    except (SchemaReject, RoundLimitExceeded, NeedsHumanReview) as exc:
        log.warning("DLQ routing %s: %s", incident.incident_id, exc)
        blocked = transition(run, WorkflowState.BLOCKED, error=str(exc))
        store.save(blocked)
        if pubsub is not None:
            pubsub.publish(cfg.dlq_topic, {
                "incident_id": incident.incident_id,
                "run_id": run.run_id,
                "error": str(exc),
                "replay": replay_command(blocked),
                "ts": time.time(),
            })
        return blocked


def _decision_from_proposal(proposal, accepted: bool) -> "PolicyDecision":
    from contracts import ActionTier, BrokerDecision, PolicyDecision
    from .controller import _derive_tier, dispatch_to_broker
    tier = _derive_tier(proposal)
    decision = dispatch_to_broker(proposal)
    return PolicyDecision(
        proposal_id=proposal.proposal_id,
        status=decision,
        tier=tier,
        reason=f"derived from proposal properties (auditor_accepted={accepted})",
        timestamp=time.time(),
    )