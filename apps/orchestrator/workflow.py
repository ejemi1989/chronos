"""Chronos workflow state machine.

States and transitions:

    RECEIVED → CLASSIFIED → DEBATING → PROPOSED → POLICY_REVIEW
                                                    │
                       ┌────────────────────────────┼────────────────────────────┐
                       ▼                            ▼                            ▼
                ALLOW_SANDBOX              REQUIRE_APPROVAL                  BLOCKED
                       │                            │                            │
                       └─────────► EXECUTING ───────┘                            │
                                    │                                          │
                                    ▼                                          ▼
                                 VERIFIED                                   CLOSED
                                    │                                          ▲
                                    └──────────────► CLOSED ───────────────────┘

Idempotency: every run is keyed by (incident_id, run_id). A second arrival
for the same key returns the existing state instead of starting over.

Persistence: WorkflowStore writes through to Firestore (production) or to a
local dict (tests). Pub/Sub arrival handlers use ``transition`` to move
forward; ``replay`` re-runs an incident from its persisted state.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Protocol

from contracts import (
    ActionProposal,
    FailureClassification,
    PolicyDecision,
    WorkflowRun,
    WorkflowState,
)

log = logging.getLogger("chronos.workflow")

# Allowed transitions: source → set of valid targets.
ALLOWED: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.RECEIVED: {WorkflowState.CLASSIFIED, WorkflowState.BLOCKED},
    WorkflowState.CLASSIFIED: {WorkflowState.DEBATING, WorkflowState.BLOCKED},
    WorkflowState.DEBATING: {WorkflowState.PROPOSED, WorkflowState.BLOCKED},
    WorkflowState.PROPOSED: {WorkflowState.POLICY_REVIEW, WorkflowState.BLOCKED},
    WorkflowState.POLICY_REVIEW: {
        WorkflowState.ALLOW_SANDBOX,
        WorkflowState.REQUIRE_APPROVAL,
        WorkflowState.BLOCKED,
    },
    WorkflowState.ALLOW_SANDBOX: {WorkflowState.EXECUTING, WorkflowState.BLOCKED},
    WorkflowState.REQUIRE_APPROVAL: {WorkflowState.EXECUTING, WorkflowState.BLOCKED},
    WorkflowState.EXECUTING: {WorkflowState.VERIFIED, WorkflowState.BLOCKED},
    WorkflowState.VERIFIED: {WorkflowState.CLOSED, WorkflowState.BLOCKED},
    WorkflowState.BLOCKED: {WorkflowState.CLOSED},
    WorkflowState.CLOSED: set(),
}

# Terminal states.
TERMINAL: frozenset[WorkflowState] = frozenset({WorkflowState.CLOSED})


class InvalidTransition(Exception):
    """Raised when a transition would violate the state machine."""


class WorkflowStore(Protocol):
    def load(self, incident_id: str, run_id: str) -> WorkflowRun | None: ...
    def latest_for_incident(self, incident_id: str) -> WorkflowRun | None: ...
    def save(self, run: WorkflowRun) -> None: ...


class InMemoryWorkflowStore:
    def __init__(self) -> None:
        self._runs: dict[tuple[str, str], WorkflowRun] = {}

    def load(self, incident_id: str, run_id: str) -> WorkflowRun | None:
        return self._runs.get((incident_id, run_id))

    def latest_for_incident(self, incident_id: str) -> WorkflowRun | None:
        latest: WorkflowRun | None = None
        for run in self._runs.values():
            if run.incident_id != incident_id:
                continue
            if latest is None or run.updated_at > latest.updated_at:
                latest = run
        return latest

    def save(self, run: WorkflowRun) -> None:
        self._runs[(run.incident_id, run.run_id)] = run


def new_run(incident_id: str) -> WorkflowRun:
    now = time.time()
    return WorkflowRun(
        incident_id=incident_id,
        run_id=f"run_{uuid.uuid4().hex[:10]}",
        state=WorkflowState.RECEIVED,
        attempt_count=0,
        created_at=now,
        updated_at=now,
    )


def transition(
    run: WorkflowRun,
    target: WorkflowState,
    *,
    classification: FailureClassification | None = None,
    proposal: ActionProposal | None = None,
    decision: PolicyDecision | None = None,
    error: str | None = None,
) -> WorkflowRun:
    """Return a NEW run object with the transition applied, or raise."""
    if target not in ALLOWED[run.state]:
        raise InvalidTransition(f"{run.state} → {target} not allowed")

    now = time.time()
    kwargs = {
        "state": target,
        "attempt_count": run.attempt_count + (1 if target == WorkflowState.DEBATING else 0),
        "updated_at": now,
        "classification": classification or run.classification,
        "last_proposal": proposal or run.last_proposal,
        "last_decision": decision or run.last_decision,
        "last_error": error if error is not None else run.last_error,
        "closed_at": now if target in TERMINAL else run.closed_at,
    }
    return run.model_copy(update=kwargs)


def replay_command(run: WorkflowRun) -> dict:
    """Deterministic replay command — same incident produces same outcome."""
    return {
        "incident_id": run.incident_id,
        "run_id": run.run_id,
        "from_state": run.state.value,
        "classification": run.classification.model_dump() if run.classification else None,
        "last_proposal": run.last_proposal.model_dump() if run.last_proposal else None,
        "last_decision": run.last_decision.model_dump() if run.last_decision else None,
    }


def is_terminal(state: WorkflowState) -> bool:
    return state in TERMINAL