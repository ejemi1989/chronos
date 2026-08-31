"""Contract schema tests — round-trip, additionalProperties, invariants."""
from __future__ import annotations

import pytest

from contracts import (
    FORBIDDEN_ACTIONS,
    ActionProposal,
    ActionTier,
    AuditCritique,
    BrokerDecision,
    BrokerVerdict,
    CounterArgument,
    FailureClassification,
    FailureType,
    Incident,
    LedgerEntry,
    PolicyDecision,
    RemediationAction,
    Severity,
    WorkflowRun,
    WorkflowState,
)


def test_incident_rejects_extra():
    with pytest.raises(Exception):
        Incident.model_validate(
            {"incident_id": "inc_abcdef", "pipeline_id": "pipe_xy",
             "error_log": "x", "context": {}, "detected_at": 0.0,
             "rogue": True}
        )


def test_incident_id_pattern():
    with pytest.raises(Exception):
        Incident.model_validate(
            {"incident_id": "bad", "pipeline_id": "pipe_xy",
             "error_log": "x", "context": {}, "detected_at": 0.0}
        )


def test_failure_type_enum():
    for v in ["SCHEMA_CHANGE", "API_TIMEOUT", "DATA_CORRUPTION", "NETWORK", "AUTH", "UNKNOWN"]:
        FailureClassification.model_validate(
            {"incident_id": "inc_abcdef", "failure_type": v, "severity": "LOW",
             "impact": ["downstream"], "root_cause": "schema drift in payload"}
        )


def test_failure_type_rejects_unknown():
    with pytest.raises(Exception):
        FailureClassification.model_validate(
            {"incident_id": "inc_abcdef", "failure_type": "FOOBAR",
             "severity": "LOW", "impact": [], "root_cause": "x" * 50}
        )


def test_proposal_pattern_enforced():
    p = {
        "proposal_id": "prop_abcdef", "incident_id": "inc_abcdef",
        "proposed_by": "debate_proposer", "round": 1,
        "action": "ROLLBACK_SCHEMA", "target": "prod.users",
        "reversible": True, "financial_impact": 0,
        "rollback": "git revert abc", "success_criteria": "200 OK",
    }
    ActionProposal.model_validate(p)


def test_proposal_rejects_bad_target():
    p = {
        "proposal_id": "prop_abcdef", "incident_id": "inc_abcdef",
        "proposed_by": "x", "round": 1,
        "action": "ROLLBACK_SCHEMA", "target": "Prod/Users",
        "reversible": True, "financial_impact": 0,
        "rollback": "x", "success_criteria": "x",
    }
    with pytest.raises(Exception):
        ActionProposal.model_validate(p)


def test_audit_critique_roundtrip():
    AuditCritique.model_validate(
        {"proposal_id": "prop_abcdef", "accept": False,
         "counterarguments": [{"point": "edge case", "severity": "HIGH", "mitigation": "x"}],
         "recommended_tier": "T1", "reason": "risky"}
    )


def test_counterargument_requires_severity():
    with pytest.raises(Exception):
        CounterArgument.model_validate(
            {"point": "x", "severity": "BOGUS", "mitigation": "y"}
        )


def test_policy_decision_required_fields():
    PolicyDecision.model_validate(
        {"proposal_id": "prop_abcdef", "status": "BLOCKED",
         "tier": "T3", "timestamp": 1.0}
    )


def test_verdict_ledger_seq_optional():
    BrokerVerdict.model_validate(
        {"proposal_id": "prop_abcdef", "decision": "BLOCKED", "reason": "x"}
    )


def test_ledger_entry_hash_pattern():
    LedgerEntry.model_validate(
        {"seq": 0, "timestamp": 1.0, "actor": "a", "action_type": "x",
         "proposal_id": "prop_abcdef", "decision": "ALLOW_SANDBOX",
         "payload": {}, "previous_hash": "0" * 64,
         "entry_hash": "a" * 64}
    )


def test_workflow_run_state_machine():
    WorkflowRun.model_validate(
        {"incident_id": "inc_abcdef", "run_id": "run_abcdef",
         "state": "RECEIVED", "attempt_count": 0,
         "created_at": 1.0, "updated_at": 1.0}
    )


def test_forbidden_actions_are_a_known_set():
    assert FORBIDDEN_ACTIONS == frozenset({"DELETE_DATA", "ALTER_PRODUCTION_SCHEMA"})


def test_remediation_action_lists_forbidden_values():
    # The enum still mentions them so an LLM that emits one gets a clear
    # validation error instead of a silent drop. The schema's allow-list is
    # what actually rejects them.
    assert RemediationAction.DELETE_DATA.value == "DELETE_DATA"
    assert RemediationAction.ALTER_PRODUCTION_SCHEMA.value == "ALTER_PRODUCTION_SCHEMA"


def test_action_tier_ordering():
    assert ActionTier.T0_SANDBOX.value == "T0"
    assert ActionTier.T3_BLOCKED.value == "T3"