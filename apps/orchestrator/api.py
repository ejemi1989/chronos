"""FastAPI entrypoint for Chronos orchestrator.

Endpoints:
  POST /incidents          — submit an incident for processing
  GET  /incidents/{id}     — read current state for an incident
  GET  /healthz            — liveness
  GET  /ledger/verify      — run verify_chain() and return result
  GET  /traces/recent      — recent OpenTelemetry spans from this process
  GET  /traces/{incident}  — spans filtered for a given incident_id
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from contracts import (
    ActionProposal,
    ActionTier,
    BrokerDecision,
    FailureClassification,
    Incident,
    WorkflowRun,
    WorkflowState,
)

from .a2a_client import submit_proposal
from .agent_registry import InMemoryAgentRegistry, build_firestore_agent_registry
from .client import InMemoryLedger
from .controller import (
    NeedsHumanReview,
    RoundLimitExceeded,
    SchemaReject,
    _derive_tier,
    dispatch_to_broker,
)
from .memory_bank import InMemoryMemoryBank, build_memory_bank, memory_entry_to_dict
from .model_armor import screen_record, screen_text
from .tracing import span
from .workflow import (
    InMemoryWorkflowStore,
    WorkflowStore,
    is_terminal,
    new_run,
    transition,
)

log = logging.getLogger("chronos.api")

app = FastAPI(title="Chronos Orchestrator", version="1.0.0")

_store: WorkflowStore = InMemoryWorkflowStore()
_ledger = InMemoryLedger()
_registry = InMemoryAgentRegistry()
_memory = InMemoryMemoryBank()


@app.on_event("startup")
async def _startup() -> None:
    """Deprecated in newer FastAPI; kept for the pinned 0.110 baseline.

    Production wiring attaches ``FirestoreWorkflowStore``,
    ``FirestoreAgentRegistry``, and the Vertex AI Memory Bank here.
    In-memory defaults suffice for tests and local dev.
    """
    global _store, _registry, _memory
    try:
        from .firestore_store import build_firestore_workflow_store
        if (fs := build_firestore_workflow_store()) is not None:
            _store = fs
    except ImportError:
        pass
    try:
        if (reg := build_firestore_agent_registry()) is not None:
            _registry = reg
    except ImportError:
        pass
    try:
        if (mb := build_memory_bank()) is not None:
            _memory = mb
    except ImportError:
        pass


class SubmitIncident(BaseModel):
    model_config = {"extra": "forbid"}
    incident_id: str
    pipeline_id: str
    error_log: str
    context: dict[str, Any] = {}
    detected_at: float = 0.0
    raw_telemetry: str | None = None


class SubmitResponse(BaseModel):
    model_config = {"extra": "forbid"}
    incident_id: str
    run_id: str
    state: WorkflowState
    proposal_id: str | None = None
    decision: BrokerDecision | None = None
    tier: ActionTier | None = None
    reason: str | None = None
    ledger_seq: int | None = None


@app.post("/incidents", response_model=SubmitResponse)
async def submit_incident(payload: SubmitIncident) -> SubmitResponse:
    # MODEL ARMOR — screen + redact before anything else touches this.
    armor = screen_record(payload.model_dump())
    redacted_log = screen_text(payload.error_log).redacted_text
    if not armor.safe:
        log.warning("model_armor flagged incident_id=%s injection=%d tool_poison=%d",
                    payload.incident_id, len(armor.injection_flags), len(armor.tool_poisoning_flags))
        raise HTTPException(
            status_code=422,
            detail={
                "error": "model_armor_rejected",
                "injection_flags": armor.injection_flags,
                "tool_poisoning_flags": armor.tool_poisoning_flags,
                "pii_redactions": armor.pii_redactions,
            },
        )

    existing = _store.latest_for_incident(payload.incident_id)
    if existing and (is_terminal(existing.state) or existing.state == WorkflowState.BLOCKED):
        raise HTTPException(status_code=409, detail=f"incident already in state {existing.state.value}")

    run = existing or new_run(payload.incident_id)
    raw = payload.raw_telemetry or redacted_log

    try:
        with span("api.classify", incident_id=payload.incident_id, parent=payload.incident_id):
            from .agents.detection import heuristic_classify
            classification = heuristic_classify(payload.incident_id, raw)
        if classification.needs_human_review:
            raise NeedsHumanReview(classification.root_cause)

        from .controller import _incident_from_telemetry
        incident = _incident_from_telemetry(classification, raw)

        with span("api.propose", incident_id=payload.incident_id, parent=payload.incident_id):
            proposal = _synthetic_proposal(classification, incident, run.run_id)
            tier = _derive_tier(proposal)

        with span("api.policy", incident_id=payload.incident_id, parent=payload.incident_id,
                  tier=tier.value):
            decision = dispatch_to_broker(proposal)

        with span("api.ledger.append", incident_id=payload.incident_id, parent=payload.incident_id):
            ledger_entry = await _ledger.append(
                actor="orchestrator",
                action_type=proposal.action.value,
                proposal_id=proposal.proposal_id,
                decision=decision,
                payload={"tier": tier.value, "round": 1},
            )

        with span("api.fsm", incident_id=payload.incident_id, parent=payload.incident_id):
            run = transition(run, WorkflowState.CLASSIFIED, classification=classification)
            run = transition(run, WorkflowState.DEBATING)
            run = transition(run, WorkflowState.PROPOSED, proposal=proposal.model_copy(update={"tier": tier}))
            if decision == BrokerDecision.BLOCKED:
                run = transition(run, WorkflowState.POLICY_REVIEW)
                run = transition(run, WorkflowState.BLOCKED)
            elif decision == BrokerDecision.REQUIRE_APPROVAL:
                run = transition(run, WorkflowState.POLICY_REVIEW)
                run = transition(run, WorkflowState.REQUIRE_APPROVAL)
                run = transition(run, WorkflowState.EXECUTING)
                run = transition(run, WorkflowState.VERIFIED)
            else:
                run = transition(run, WorkflowState.POLICY_REVIEW)
                run = transition(run, WorkflowState.ALLOW_SANDBOX)
                run = transition(run, WorkflowState.EXECUTING)
                run = transition(run, WorkflowState.VERIFIED)
            run = transition(run, WorkflowState.CLOSED)
            _store.save(run)

        with span("api.memory.append", incident_id=payload.incident_id, parent=payload.incident_id):
            _memory.append(
                app_name="chronos",
                user_id="chronos",
                summary=f"{classification.failure_type.value} → {decision.value}",
                content=(
                    f"incident={payload.incident_id} pipeline={payload.pipeline_id} "
                    f"root_cause={classification.root_cause} "
                    f"action={proposal.action.value} tier={tier.value} decision={decision.value}"
                ),
                incident_id=payload.incident_id,
                failure_type=classification.failure_type.value,
                extra={"ledger_seq": ledger_entry.seq, "tier": tier.value},
            )

        return SubmitResponse(
            incident_id=run.incident_id, run_id=run.run_id, state=run.state,
            proposal_id=proposal.proposal_id, decision=decision, tier=tier,
            reason=f"tier {tier.value} → {decision.value}",
            ledger_seq=ledger_entry.seq,
        )

    except (SchemaReject, RoundLimitExceeded, NeedsHumanReview) as exc:
        log.warning("submit failed: %s", exc)
        run = transition(run, WorkflowState.BLOCKED, error=str(exc))
        _store.save(run)
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/incidents/{incident_id}", response_model=WorkflowRun)
async def get_incident(incident_id: str) -> WorkflowRun:
    run = _store.latest_for_incident(incident_id)
    if run is None:
        raise HTTPException(status_code=404, detail="not found")
    return run


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "ts": time.time()}


@app.get("/ledger/verify")
async def verify_ledger() -> dict:
    ok = await _ledger.verify_chain()
    head = await _ledger.head()
    return {"ok": ok, "head_seq": head.seq if head else None}


@app.get("/traces/recent")
async def traces_recent(limit: int = 100) -> dict:
    """Return the most recent OpenTelemetry spans emitted by this process."""
    from .tracing import get_recent_spans
    return {"spans": get_recent_spans(limit)}


@app.get("/traces/{incident_id}")
async def traces_for_incident(incident_id: str) -> dict:
    """Return the reasoning-chain spans for an incident, ordered chronologically."""
    from .tracing import get_recent_spans
    spans = get_recent_spans(2000)
    matched = [
        s for s in spans
        if s.get("attributes", {}).get("incident_id") == incident_id
    ]
    return {"incident_id": incident_id, "count": len(matched), "spans": matched}


# ----- Agent Registry (GEAP capability: discovery + versioning) -----


@app.get("/registry/agents")
async def registry_list(
    capability: str | None = None,
    owner: str | None = None,
    tier: str | None = None,
) -> dict:
    """List discoverable agents. Filter by capability, owner, or tier."""
    records = _registry.list(capability=capability, owner=owner, tier=tier)
    return {
        "count": len(records),
        "agents": [_record_to_dict(r) for r in records],
    }


@app.get("/registry/agents/{agent_id}")
async def registry_get(agent_id: str, version: int | None = None) -> dict:
    """Get a specific agent (latest version by default)."""
    rec = _registry.get(agent_id, version=version)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"agent {agent_id} not found")
    return _record_to_dict(rec)


@app.get("/registry/agents/{agent_id}/versions")
async def registry_versions(agent_id: str) -> dict:
    """List every version of an agent."""
    versions = _registry.versions(agent_id)
    if not versions:
        raise HTTPException(status_code=404, detail=f"agent {agent_id} not found")
    return {
        "agent_id": agent_id,
        "versions": [_record_to_dict(v) for v in versions],
    }


def _record_to_dict(r) -> dict:
    return {
        "agent_id": r.agent_id,
        "version": r.version,
        "owner": r.owner,
        "tier": r.tier,
        "deprecated": r.deprecated,
        "published_at": r.published_at,
        "content_hash": r.content_hash,
        "card": {
            "name": r.card.name,
            "version": r.card.version,
            "description": r.card.description,
            "capabilities": list(r.card.capabilities),
            "target": r.card.target,
            "output_schema": r.card.output_schema,
            "endpoint": r.card.endpoint,
            "extra": dict(r.card.extra),
        },
    }


# ----- Memory Bank (GEAP capability: persistent cross-session context) -----


@app.get("/memory/recent")
async def memory_recent(limit: int = 20) -> dict:
    """List the most recent memory entries."""
    return {"entries": [memory_entry_to_dict(e) for e in _memory.recent(limit)]}


@app.get("/memory/search")
async def memory_search(q: str, limit: int = 10) -> dict:
    """Search the memory bank by free-text query."""
    return {"query": q, "hits": [memory_entry_to_dict(e) for e in _memory.search(q, limit=limit)]}


@app.get("/memory/recall/{incident_id}")
async def memory_recall(incident_id: str, limit: int = 10) -> dict:
    """Recall memories associated with a specific incident."""
    return {"incident_id": incident_id, "memories": [memory_entry_to_dict(e) for e in _memory.recall_for(incident_id, limit=limit)]}


def _synthetic_proposal(
    classification: FailureClassification,
    incident: Incident,
    run_id: str,
) -> ActionProposal:
    """Produce a safe proposal from the classification (no LLM required)."""
    from contracts import RemediationAction
    action_map = {
        "SCHEMA_CHANGE": RemediationAction.ROLLBACK_SCHEMA,
        "API_TIMEOUT": RemediationAction.REPLAY_BATCH,
        "AUTH": RemediationAction.ROTATE_TOKEN,
        "DATA_CORRUPTION": RemediationAction.REPLAY_BATCH,
        "NETWORK": RemediationAction.REPLAY_BATCH,
        "UNKNOWN": RemediationAction.REPLAY_BATCH,
    }
    action = action_map[classification.failure_type.value]
    return ActionProposal(
        proposal_id=f"prop_{run_id[4:10]}",
        incident_id=classification.incident_id,
        proposed_by="synthetic",
        round=1,
        action=action,
        target=f"prod.{incident.pipeline_id[5:]}",
        reversible=True,
        financial_impact=0,
        rollback="automatic rollback via checkpoint",
        success_criteria="error rate returns to baseline for 5 minutes",
        rationale=f"{classification.failure_type.value} detected: {classification.root_cause}",
    )