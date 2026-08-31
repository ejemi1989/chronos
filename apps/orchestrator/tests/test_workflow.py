"""Workflow state machine tests."""
from __future__ import annotations

import pytest

from contracts import (
    ActionProposal,
    ActionTier,
    FailureClassification,
    FailureType,
    Incident,
    PolicyDecision,
    RemediationAction,
    Severity,
    WorkflowRun,
    WorkflowState,
)
from orchestrator.workflow import (
    ALLOWED,
    InMemoryWorkflowStore,
    InvalidTransition,
    TERMINAL,
    is_terminal,
    new_run,
    replay_command,
    transition,
)


def _incident() -> Incident:
    return Incident(
        incident_id="inc_abcdef", pipeline_id="pipe_xyz1",
        error_log="boom", context={}, detected_at=0.0,
    )


def _class() -> FailureClassification:
    return FailureClassification(
        incident_id="inc_abcdef", failure_type=FailureType.SCHEMA_CHANGE,
        severity=Severity.HIGH, impact=["downstream"],
        root_cause="schema drift in upstream payload",
    )


def _prop() -> ActionProposal:
    return ActionProposal(
        proposal_id="prop_abcdef", incident_id="inc_abcdef",
        proposed_by="debate_proposer", round=1,
        action=RemediationAction.ROLLBACK_SCHEMA, target="prod.users",
        reversible=True, financial_impact=0,
        rollback="git revert abc", success_criteria="200 OK",
    )


def test_new_run_starts_received():
    run = new_run("inc_abcdef")
    assert run.state == WorkflowState.RECEIVED
    assert run.attempt_count == 0


def test_valid_transition_classified():
    run = new_run("inc_abcdef")
    run2 = transition(run, WorkflowState.CLASSIFIED, classification=_class())
    assert run2.state == WorkflowState.CLASSIFIED
    assert run2.classification == _class()


def test_invalid_transition_raises():
    run = new_run("inc_abcdef")
    with pytest.raises(InvalidTransition):
        transition(run, WorkflowState.EXECUTING)  # skips everything


def test_terminal_states_have_no_exits():
    for s in TERMINAL:
        assert ALLOWED[s] == set()


def test_blocked_can_only_go_to_closed():
    assert ALLOWED[WorkflowState.BLOCKED] == {WorkflowState.CLOSED}


def test_idempotent_transition_keeps_classification():
    run = new_run("inc_abcdef")
    run = transition(run, WorkflowState.CLASSIFIED, classification=_class())
    run = transition(run, WorkflowState.DEBATING)
    assert run.classification == _class()


def test_replay_command_includes_run_id():
    run = new_run("inc_abcdef")
    cmd = replay_command(run)
    assert cmd["incident_id"] == "inc_abcdef"
    assert cmd["from_state"] == "RECEIVED"


def test_in_memory_store_roundtrip():
    s = InMemoryWorkflowStore()
    run = new_run("inc_abcdef")
    s.save(run)
    assert s.load(run.incident_id, run.run_id) == run


def test_is_terminal_classifier():
    assert is_terminal(WorkflowState.CLOSED)
    assert not is_terminal(WorkflowState.BLOCKED)
    assert not is_terminal(WorkflowState.DEBATING)