"""DetectionAgent — turns raw telemetry into a FailureClassification.

If the LLM cannot classify the failure with high confidence, it routes the
incident to "needs human review" — never to automatic repair.

This module builds a wrapper around the GEAP Interactions API
(``google-genai >= 2.3.0``). The agent_id ``chronos.detection_agent`` is
provisioned once on Gemini Enterprise Agent Platform; production wiring
authenticates via ADC and reads ``GOOGLE_CLOUD_PROJECT`` +
``VERTEX_AI_LOCATION``. Tests use ``OfflineInteractionsClient``.
"""
from __future__ import annotations

import logging
import re
import os
from typing import Any

from contracts import FailureClassification, FailureType, Severity

from ..interactions_agent import (
    InteractionsAgent,
    OfflineInteractionsClient,
    offline_responder_from_factory,
)

log = logging.getLogger("chronos.detection")

SYSTEM_PROMPT = """You are DetectionAgent. Analyze the provided pipeline error log.
Classify the failure with:
  failure_type ∈ {SCHEMA_CHANGE, API_TIMEOUT, DATA_CORRUPTION, NETWORK, AUTH, UNKNOWN}
  severity     ∈ {CRITICAL, HIGH, MEDIUM, LOW}
  impact       list of affected downstream systems (kebab-case identifiers)
  root_cause   1–2 sentence summary
Set needs_human_review=true if the log is ambiguous, contains credentials,
or describes an action you cannot classify with confidence. Otherwise false.
Output valid JSON that matches the schema."""


AGENT_ID = "chronos.detection_agent"


# Lightweight heuristic fallback used when no LLM is wired (tests / local
# dev without GCP credentials).
_HEURISTIC_PATTERNS: list[tuple[re.Pattern, FailureType, Severity]] = [
    (re.compile(r"\bschema\b|\bcolumn\b|\bfield\b", re.I), FailureType.SCHEMA_CHANGE, Severity.HIGH),
    (re.compile(r"\btimeout\b|\bdeadline\b|\bETIMEDOUT\b", re.I), FailureType.API_TIMEOUT, Severity.MEDIUM),
    (re.compile(r"\bcorrupt|\bchecksum\b|\bCRC\b", re.I), FailureType.DATA_CORRUPTION, Severity.CRITICAL),
    (re.compile(r"\bnetwork|\bDNS|\bconnection refused\b", re.I), FailureType.NETWORK, Severity.MEDIUM),
    (re.compile(r"\b401\b|\b403\b|\bJWT\b|\bauth\b", re.I), FailureType.AUTH, Severity.HIGH),
]


def heuristic_classify(incident_id: str, raw: str) -> FailureClassification:
    for pat, ftype, sev in _HEURISTIC_PATTERNS:
        if pat.search(raw):
            return FailureClassification(
                incident_id=incident_id,
                failure_type=ftype,
                severity=sev,
                impact=["downstream"],
                root_cause=(raw[:200].strip() or f"{ftype.value} observed")[:200],
            )
    return FailureClassification(
        incident_id=incident_id,
        failure_type=FailureType.UNKNOWN,
        severity=Severity.LOW,
        impact=[],
        root_cause=(raw[:200].strip() or "unknown failure with no telemetry"),
        needs_human_review=True,
    )


def build() -> InteractionsAgent:
    """Build the production DetectionAgent backed by the GEAP Interactions API.

    The agent_id is ``chronos.detection_agent``; response_format is the
    ``FailureClassification`` Pydantic schema. ``system_instruction`` and
    any tools would be passed turn-scoped at runtime — see
    ``InteractionsAgent.run()``.
    """
    return InteractionsAgent(
        agent_id=AGENT_ID,
        response_schema=FailureClassification,
        system_instruction=SYSTEM_PROMPT,
    )


def build_offline(incident_id_for_logs: str = "offline") -> InteractionsAgent:
    """Build an offline (deterministic) DetectionAgent for tests.

    Uses the local heuristic to produce the JSON the Interactions API
    would return in production. The factory reads the telemetry out of
    the ``input`` kwarg so tests look identical to production.
    """
    def factory(kwargs: dict[str, Any]) -> dict[str, Any]:
        text = kwargs.get("input", "") or ""
        # Heuristic needs an incident_id — use a placeholder; the real
        # incident_id is supplied by the orchestrator when constructing
        # the prompt and is reconciled downstream.
        fc = heuristic_classify(incident_id_for_logs, text)
        return fc.model_dump()

    client = OfflineInteractionsClient(
        responders={AGENT_ID: offline_responder_from_factory(factory)}
    )
    return InteractionsAgent(
        agent_id=AGENT_ID,
        response_schema=FailureClassification,
        system_instruction=SYSTEM_PROMPT,
        client=client,
    )