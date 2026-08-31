"""DebateAuditor — attacks the Proposer's plan.

The Auditor must receive the original incident AND the proposed plan, not
just a prose summary. It returns a structured critique with concrete
counterarguments; the controller caps the debate at 3 rounds.

Wrapped via the GEAP Interactions API. Agent id
``chronos.debate_auditor`` is provisioned on the Agent Platform; tests
use ``OfflineInteractionsClient``.
"""
from __future__ import annotations

import logging
from typing import Any

from contracts import AuditCritique

from ..interactions_agent import (
    InteractionsAgent,
    OfflineInteractionsClient,
    offline_responder_from_factory,
)

log = logging.getLogger("chronos.auditor")

SYSTEM_PROMPT = """You are the Auditor. Attack the Proposer's plan. The goal is
to HARDEN the plan, not to win the argument.

Examine the proposal against the original incident and the FailureClassification.
Find flaws in:
  • edge cases       — does it handle the failure mode AND its neighbors?
  • hidden deps      — does any downstream service break?
  • resources        — quota, timeouts, partial rollouts
  • security         — exposure window, blast radius, audit gaps
  • rollback         — is rollback actually tested? idempotent? reversible?

Return 3–5 concrete counterarguments, each with severity and a mitigation.
Set:
  • accept              — true only if the plan is production-ready
  • counterarguments     — array of {point, severity, mitigation}
  • recommended_tier     — T0/T1/T2/T3 if you want to make the action safer
  • reason               — one paragraph summary

NEVER propose DELETE_DATA or ALTER_PRODUCTION_SCHEMA. NEVER recommend a
riskier tier than the Proposer chose. Output valid JSON matching the schema."""


AGENT_ID = "chronos.debate_auditor"


def build() -> InteractionsAgent:
    """Production DebateAuditor backed by the Interactions API."""
    return InteractionsAgent(
        agent_id=AGENT_ID,
        response_schema=AuditCritique,
        system_instruction=SYSTEM_PROMPT,
    )


def build_offline(accept: bool = True, *, reason: str = "Plan is production-ready.") -> InteractionsAgent:
    """Offline deterministic auditor used by tests."""
    def factory(_kwargs: dict[str, Any]) -> dict[str, Any]:
        return {
            "proposal_id": "prop_offline",
            "accept": accept,
            "counterarguments": [],
            "recommended_tier": None,
            "reason": reason,
        }

    client = OfflineInteractionsClient(
        responders={AGENT_ID: offline_responder_from_factory(factory)}
    )
    return InteractionsAgent(
        agent_id=AGENT_ID,
        response_schema=AuditCritique,
        system_instruction=SYSTEM_PROMPT,
        client=client,
    )