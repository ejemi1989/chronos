"""Chronos controller — orchestrates detection + up to 3 proposer/auditor rounds.

State machine
-------------
RECEIVED → CLASSIFIED → DEBATING → PROPOSED → POLICY_REVIEW
                                                 ├─→ ALLOW_SANDBOX → EXECUTING → VERIFIED → CLOSED
                                                 ├─→ REQUIRE_APPROVAL → EXECUTING → VERIFIED → CLOSED
                                                 └─→ BLOCKED → CLOSED

The controller is the SOLE OWNER of the three-round limit. The model never
holds an execution tool. Any T3 / forbidden action is discarded here, then
the broker structurally blocks it on the wire — defense in depth.

Every step emits an OpenTelemetry span via :mod:`apps.orchestrator.tracing`
so the reasoning chain is auditable end-to-end.

Agents are GEAP Interactions API wrappers (``InteractionsAgent``) targeting
provisioned agents on the Agent Platform. Tests use ``build_offline_*``
helpers that route through ``OfflineInteractionsClient`` for deterministic
responses without GCP credentials.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

from contracts import (
    FORBIDDEN_ACTIONS,
    ActionProposal,
    ActionTier,
    AuditCritique,
    BrokerDecision,
    FailureClassification,
    Incident,
)
from .agents import auditor, detection, proposer
from .interactions_agent import InteractionsAgent, InteractionsError
from .tracing import traced, span

log = logging.getLogger("chronos.controller")

MAX_ROUNDS = 3
DEFAULT_TIMEOUT_S = 30.0  # GEAP Interactions has higher latency than ADK Runner


class SchemaReject(Exception):
    """LLM output failed strict Pydantic validation."""


class RoundLimitExceeded(Exception):
    """The auditor never accepted within MAX_ROUNDS."""


class NeedsHumanReview(Exception):
    """DetectionAgent marked the incident as needing human review."""


@dataclass
class Pipeline:
    """A bundle of the three InteractionsAgents the controller drives.

    Production wires ``detection.build()`` etc.; tests wire
    ``detection.build_offline()``. The session_service and memory_service
    attributes are kept for backward compatibility with the previous
    ADK-Runner-based interface.
    """
    detection_agent: InteractionsAgent
    proposer_agent: InteractionsAgent
    auditor_agent: InteractionsAgent
    session_service: object | None = None
    memory_service: object | None = None


@dataclass
class ControllerResult:
    classification: FailureClassification
    incident: Incident
    proposal: ActionProposal
    rounds: int
    accepted: bool


def build_pipeline() -> Pipeline:
    """Build the production pipeline targeting GEAP Interactions agents.

    Returns a Pipeline with production InteractionsAgent instances. The
    ``client`` attribute on each is lazy — the first ``.run()`` call
    authenticates via ADC and constructs the genai.Client on demand.
    """
    return Pipeline(
        detection_agent=detection.build(),
        proposer_agent=proposer.build(),
        auditor_agent=auditor.build(),
    )


def build_offline_pipeline(
    incident_id: str = "inc_offline01",
    *,
    auditor_accepts: bool = True,
) -> Pipeline:
    """Build an offline pipeline for tests + local dev (no GCP creds)."""
    return Pipeline(
        detection_agent=detection.build_offline(incident_id_for_logs=incident_id),
        proposer_agent=proposer.build_offline(incident_id=incident_id),
        auditor_agent=auditor.build_offline(accept=auditor_accepts),
    )


@traced("controller.run_incident")
async def run_incident(
    raw_telemetry: str,
    pipeline: Pipeline | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> ControllerResult:
    """Run the full detection → debate loop, capped at MAX_ROUNDS.

    The output of DetectionAgent is a FailureClassification; the debate
    loop produces an ActionProposal. Tier is derived from structural
    proposal properties — never trusted from the model.
    """
    if pipeline is None:
        pipeline = build_pipeline()

    session_id = f"sess-{uuid.uuid4()}"
    with span("session.create", session_id):
        # In production, the session service records the session for
        # long-running cross-week context; tests use a no-op service.
        if getattr(pipeline, "session_service", None) is not None:
            try:
                await pipeline.session_service.create_session(
                    app_name="chronos",
                    user_id="chronos",
                    session_id=session_id,
                )
            except Exception:  # pragma: no cover — best-effort
                pass

    # 1. DETECTION
    with span("phase.detection", session_id):
        try:
            det_result = await asyncio.wait_for(
                pipeline.detection_agent.run_async(raw_telemetry),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError as exc:
            raise SchemaReject("detection timeout") from exc
        except InteractionsError as exc:
            raise SchemaReject(f"detection interactions: {exc}") from exc

        if det_result.parsed is None:
            raise SchemaReject("detection returned no parsed output")
        classification = det_result.parsed
        if classification.needs_human_review:
            raise NeedsHumanReview(
                f"classification flagged for human review: {classification.root_cause}"
            )

        incident = _incident_from_telemetry(classification, raw_telemetry)

    # 2. DEBATE — at most 3 rounds
    last_proposal: ActionProposal | None = None
    for round_idx in range(1, MAX_ROUNDS + 1):
        with span(f"phase.debate.round.{round_idx}", session_id):
            try:
                prop_result = await asyncio.wait_for(
                    pipeline.proposer_agent.run_async(
                        f"Classification: {classification.model_dump_json()}. Round {round_idx} of {MAX_ROUNDS}."
                    ),
                    timeout=timeout_s,
                )
                crit_result = await asyncio.wait_for(
                    pipeline.auditor_agent.run_async(
                        f"Critique round {round_idx}. Auditor, attack the last proposal."
                    ),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError as exc:
                raise SchemaReject(f"round {round_idx} timeout") from exc
            except InteractionsError as exc:
                raise SchemaReject(f"round {round_idx} interactions: {exc}") from exc

            if prop_result.parsed is None:
                raise SchemaReject(f"round {round_idx}: no proposal parsed")
            proposal = prop_result.parsed.model_copy(update={"round": round_idx})
            proposal = proposal.model_copy(update={"tier": _derive_tier(proposal)})

            if proposal.action.value in FORBIDDEN_ACTIONS:
                log.warning("proposer emitted forbidden action %s — discarding", proposal.action)
                continue

            if crit_result.parsed is None:
                raise SchemaReject(f"round {round_idx}: no critique parsed")
            critique = crit_result.parsed

            last_proposal = proposal
            if critique.accept:
                return ControllerResult(classification, incident, proposal, round_idx, True)

            if critique.recommended_tier and _tier_rank(critique.recommended_tier) > _tier_rank(proposal.tier):
                last_proposal = proposal.model_copy(update={"tier": critique.recommended_tier})

    if last_proposal is None:
        raise RoundLimitExceeded("no proposal accepted within MAX_ROUNDS")
    return ControllerResult(classification, incident, last_proposal, MAX_ROUNDS, False)


def _tier_rank(tier: ActionTier) -> int:
    return {ActionTier.T0_SANDBOX: 0, ActionTier.T1_APPROVAL: 1, ActionTier.T2_HIGH_RISK: 2, ActionTier.T3_BLOCKED: 3}[tier]


def _incident_from_telemetry(classification: FailureClassification, raw: str) -> Incident:
    """Best-effort Incident reconstruction from raw telemetry."""
    return Incident(
        incident_id=classification.incident_id,
        pipeline_id=f"pipe_{classification.incident_id[4:8]}",
        error_log=raw[:65536],
        context={"failure_type": classification.failure_type.value,
                 "severity": classification.severity.value},
        detected_at=0.0,
    )


def _derive_tier(proposal: ActionProposal) -> ActionTier:
    """Deterministic tier derivation from structural proposal properties."""
    if proposal.action.value in FORBIDDEN_ACTIONS:
        return ActionTier.T3_BLOCKED
    if proposal.financial_impact > 10000:
        return ActionTier.T2_HIGH_RISK
    if not proposal.reversible:
        return ActionTier.T1_APPROVAL
    return ActionTier.T0_SANDBOX


def dispatch_to_broker(proposal: ActionProposal) -> BrokerDecision:
    """Local stub mirroring the Go broker's tier → decision mapping."""
    tier = _derive_tier(proposal)
    if tier == ActionTier.T3_BLOCKED:
        return BrokerDecision.BLOCKED
    if tier in (ActionTier.T1_APPROVAL, ActionTier.T2_HIGH_RISK):
        return BrokerDecision.REQUIRE_APPROVAL
    return BrokerDecision.ALLOW_SANDBOX