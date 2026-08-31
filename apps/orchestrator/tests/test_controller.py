"""Controller logic tests — tier derivation, forbidden drop, 3-round cap."""
from __future__ import annotations

import pytest

from contracts import (
    ActionProposal,
    ActionTier,
    BrokerDecision,
    FORBIDDEN_ACTIONS,
    RemediationAction,
    Severity,
)
from orchestrator import (
    NeedsHumanReview,
    RoundLimitExceeded,
    SchemaReject,
    _derive_tier,
    _tier_rank,
    dispatch_to_broker,
)


def _mk(action="ROLLBACK_SCHEMA", target="prod.users", reversible=True,
        financial_impact=0, **kw):
    return ActionProposal(
        proposal_id="prop_abcdef", incident_id="inc_abcdef",
        proposed_by="debate_proposer", round=1,
        action=RemediationAction(action), target=target,
        reversible=reversible, financial_impact=financial_impact,
        rollback="git revert", success_criteria="200 OK",
        **kw,
    )


def test_derive_tier_T0_reversible():
    assert _derive_tier(_mk(reversible=True, financial_impact=0)) == ActionTier.T0_SANDBOX


def test_derive_tier_T1_non_reversible():
    assert _derive_tier(_mk(reversible=False, financial_impact=0)) == ActionTier.T1_APPROVAL


def test_derive_tier_T2_high_financial_impact():
    assert _derive_tier(_mk(reversible=True, financial_impact=10001)) == ActionTier.T2_HIGH_RISK


def test_derive_tier_T3_forbidden_action():
    for action in FORBIDDEN_ACTIONS:
        assert _derive_tier(_mk(action=action)) == ActionTier.T3_BLOCKED


def test_dispatch_t0_allow_sandbox():
    p = _mk(reversible=True)
    assert dispatch_to_broker(p) == BrokerDecision.ALLOW_SANDBOX


def test_dispatch_t1_require_approval():
    p = _mk(reversible=False)
    assert dispatch_to_broker(p) == BrokerDecision.REQUIRE_APPROVAL


def test_dispatch_t2_require_approval():
    p = _mk(financial_impact=50000)
    assert dispatch_to_broker(p) == BrokerDecision.REQUIRE_APPROVAL


def test_dispatch_t3_blocked():
    p = _mk(action="DELETE_DATA")
    assert dispatch_to_broker(p) == BrokerDecision.BLOCKED


def test_tier_rank_monotonic():
    assert _tier_rank(ActionTier.T0_SANDBOX) < _tier_rank(ActionTier.T1_APPROVAL)
    assert _tier_rank(ActionTier.T1_APPROVAL) < _tier_rank(ActionTier.T2_HIGH_RISK)
    assert _tier_rank(ActionTier.T2_HIGH_RISK) < _tier_rank(ActionTier.T3_BLOCKED)


def test_schema_reject_subclass():
    assert issubclass(SchemaReject, Exception)


def test_round_limit_exceeded_subclass():
    assert issubclass(RoundLimitExceeded, Exception)


def test_needs_human_review_subclass():
    assert issubclass(NeedsHumanReview, Exception)