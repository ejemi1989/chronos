"""DebateProposer — emits an ActionProposal.

Constraints baked into the prompt:
:
  - Never propose DELETE_DATA or ALTER_PRODUCTION_SCHEMA (forbidden).
  - Always include rollback and success_criteria.
  - Action must come from the enum: ROLLBACK_SCHEMA, REPLAY_BATCH, ROTATE_TOKEN.

The proposer holds NO execution tool. Its output is a proposal, not an action.

This module wraps the GEAP Interactions API. The agent_id
``chronos.debate_proposer`` is provisioned on the Agent Platform; tests
use ``OfflineInteractionsClient``.
"""
from __future__ import annotations

import logging
from typing import Any

from contracts import ActionProposal

from ..interactions_agent import (
    InteractionsAgent,
    OfflineInteractionsClient,
    offline_responder_from_factory,
)

log = logging.getLogger("chronos.proposer")

SYSTEM_PROMPT = """You are the Proposer in a Proposer/Auditor debate.

Given a FailureClassification and the original incident context, propose a
single repair strategy as an ActionProposal.

Allowed actions (you may ONLY use these):
  • ROLLBACK_SCHEMA   — revert a schema change
  • REPLAY_BATCH      — re-run a failed batch with a checkpoint
  • ROTATE_TOKEN      — rotate an expired or compromised credential

NEVER propose DELETE_DATA or ALTER_PRODUCTION_SCHEMA — these are forbidden.

You MUST provide:
  • action                (one of the three above)
  • target                (kebab-case resource identifier)
  • reversible            (true if a clean rollback exists)
  • financial_impact      (USD, integer)
  • rollback              (step-by-step recovery instructions)
  • success_criteria      (objective signal that the fix worked)
  • rationale             (one short paragraph)

Be prepared to defend against Auditor counterarguments. Focus on speed,
correctness, and minimal disruption. Output valid JSON matching the schema."""


AGENT_ID = "chronos.debate_proposer"


def build() -> InteractionsAgent:
    """Production DebateProposer backed by the Interactions API."""
    return InteractionsAgent(
        agent_id=AGENT_ID,
        response_schema=ActionProposal,
        system_instruction=SYSTEM_PROMPT,
    )


def build_offline(incident_id: str = "offline", proposal_round: int = 1) -> InteractionsAgent:
    """Offline Deterministic proposer used by tests.

    Picks the safest action based on the failure type encoded in the
    telemetry string. The factory reads the input kwargs just like the
    real Interactions API would.
    """
    from contracts import RemediationAction

    def factory(kwargs: dict[str, Any]) -> dict[str, Any]:
        text = (kwargs.get("input", "") or "").lower()
        if "schema" in text or "column" in text:
            action = RemediationAction.ROLLBACK_SCHEMA
        elif "auth" in text or "401" in text or "403" in text or "jwt" in text:
            action = RemediationAction.ROTATE_TOKEN
        else:
            action = RemediationAction.REPLAY_BATCH
        return {
            "proposal_id": f"prop_{proposal_round:06d}",
            "incident_id": incident_id,
            "proposed_by": AGENT_ID,
            "round": proposal_round,
            "action": action.value,
            "target": "prod.pipeline",
            "reversible": True,
            "financial_impact": 0,
            "rollback": "automatic rollback via checkpoint",
            "success_criteria": "error rate returns to baseline for 5 minutes",
            "rationale": f"{action.value} selected because telemetry suggests a fixable failure.",
        }

    client = OfflineInteractionsClient(
        responders={AGENT_ID: offline_responder_from_factory(factory)}
    )
    return InteractionsAgent(
        agent_id=AGENT_ID,
        response_schema=ActionProposal,
        system_instruction=SYSTEM_PROMPT,
        client=client,
    )