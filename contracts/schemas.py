# Chronos contracts — Pydantic v2 schemas (single source of truth)
#
# This file is the Python twin of contracts/*.schema.json. Both stay in sync
# via the tests in apps/orchestrator/tests/test_contracts.py.

from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class ActionTier(str, Enum):
    T0_SANDBOX = "T0"   # reversible, sandbox only
    T1_APPROVAL = "T1"  # reversible, requires approval
    T2_HIGH_RISK = "T2"  # irreversible, requires approval + ticket
    T3_BLOCKED = "T3"   # structurally unreachable — blocked by code


class BrokerDecision(str, Enum):
    ALLOW_SANDBOX = "ALLOW_SANDBOX"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    BLOCKED = "BLOCKED"


class FailureType(str, Enum):
    SCHEMA_CHANGE = "SCHEMA_CHANGE"
    API_TIMEOUT = "API_TIMEOUT"
    DATA_CORRUPTION = "DATA_CORRUPTION"
    NETWORK = "NETWORK"
    AUTH = "AUTH"
    UNKNOWN = "UNKNOWN"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RemediationAction(str, Enum):
    """The only action types the model may ever propose."""
    ROLLBACK_SCHEMA = "ROLLBACK_SCHEMA"
    REPLAY_BATCH = "REPLAY_BATCH"
    ROTATE_TOKEN = "ROTATE_TOKEN"
    # DELETE_DATA and ALTER_PRODUCTION_SCHEMA are deliberately NOT in this
    # enum. The schema itself forbids them. The Go broker structurally
    # blocks them. Both layers agree.
    DELETE_DATA = "DELETE_DATA"  # present for validation completeness; rejected
    ALTER_PRODUCTION_SCHEMA = "ALTER_PRODUCTION_SCHEMA"  # present for validation completeness; rejected


# Forbidden actions — broker MUST reject these with no executor path.
FORBIDDEN_ACTIONS: frozenset[str] = frozenset({"DELETE_DATA", "ALTER_PRODUCTION_SCHEMA"})


class Incident(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    incident_id: str = Field(pattern=r"^inc_[A-Za-z0-9]{6,}$")
    pipeline_id: str = Field(pattern=r"^pipe_[A-Za-z0-9]{4,}$")
    error_log: str = Field(min_length=1, max_length=65536)
    context: dict[str, Any] = Field(default_factory=dict)
    detected_at: float


class FailureClassification(BaseModel):
    """Output of DetectionAgent."""
    model_config = ConfigDict(extra="forbid")
    incident_id: str = Field(pattern=r"^inc_[A-Za-z0-9]{6,}$")
    failure_type: FailureType
    severity: Severity
    impact: list[str] = Field(default_factory=list, max_length=32)
    root_cause: str = Field(min_length=10, max_length=500)
    needs_human_review: bool = False


class ActionProposal(BaseModel):
    """Output of DebateProposer; passed verbatim to the Go Action Broker."""
    model_config = ConfigDict(extra="forbid")
    proposal_id: str = Field(pattern=r"^prop_[A-Za-z0-9]{6,}$")
    incident_id: str = Field(pattern=r"^inc_[A-Za-z0-9]{6,}$")
    proposed_by: str = Field(min_length=1, max_length=128)
    round: int = Field(ge=1, le=3)
    action: RemediationAction
    target: str = Field(pattern=r"^[a-z][a-z0-9._-]{1,63}$")
    reversible: bool
    financial_impact: int = Field(ge=0)
    rollback: str = Field(min_length=1, max_length=2000)
    success_criteria: str = Field(min_length=1, max_length=2000)
    rationale: str | None = Field(default=None, max_length=4000)


class CounterArgument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    point: str = Field(min_length=1, max_length=400)
    severity: Severity
    mitigation: str = Field(min_length=1, max_length=400)


class AuditCritique(BaseModel):
    """Output of DebateAuditor."""
    model_config = ConfigDict(extra="forbid")
    proposal_id: str = Field(pattern=r"^prop_[A-Za-z0-9]{6,}$")
    accept: bool
    counterarguments: list[CounterArgument] = Field(default_factory=list, max_length=8)
    recommended_tier: ActionTier | None = None
    reason: str = Field(min_length=1, max_length=1000)


class PolicyDecision(BaseModel):
    """Output of the Go Action Broker."""
    model_config = ConfigDict(extra="forbid")
    proposal_id: str = Field(pattern=r"^prop_[A-Za-z0-9]{6,}$")
    status: BrokerDecision
    tier: ActionTier
    reason: str | None = Field(default=None, max_length=500)
    timestamp: float
    approver: str | None = None
    ledger_seq: int | None = None


class BrokerVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str = Field(pattern=r"^prop_[A-Za-z0-9]{6,}$")
    decision: BrokerDecision
    reason: str
    ledger_seq: int | None = None


class LedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seq: int = Field(ge=0)
    timestamp: float
    actor: str
    action_type: str
    proposal_id: str
    decision: BrokerDecision
    payload: dict[str, Any]
    previous_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    entry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class WorkflowState(str, Enum):
    RECEIVED = "RECEIVED"
    CLASSIFIED = "CLASSIFIED"
    DEBATING = "DEBATING"
    PROPOSED = "PROPOSED"
    POLICY_REVIEW = "POLICY_REVIEW"
    ALLOW_SANDBOX = "ALLOW_SANDBOX"
    REQUIRE_APPROVAL = "APPROVAL_REQUIRED"
    BLOCKED = "BLOCKED"
    EXECUTING = "EXECUTING"
    VERIFIED = "VERIFIED"
    CLOSED = "CLOSED"


class WorkflowRun(BaseModel):
    """A single incident processing run — persisted to Firestore for idempotency."""
    model_config = ConfigDict(extra="forbid")
    incident_id: str = Field(pattern=r"^inc_[A-Za-z0-9]{6,}$")
    run_id: str = Field(pattern=r"^run_[A-Za-z0-9]{6,}$")
    state: WorkflowState
    attempt_count: int = Field(ge=0)
    classification: FailureClassification | None = None
    last_proposal: ActionProposal | None = None
    last_decision: PolicyDecision | None = None
    last_error: str | None = None
    created_at: float
    updated_at: float
    closed_at: float | None = None