// Package types defines shared value types used by the broker internals.
// It has no imports from other internal packages so registry and policy can
// both depend on it without cycles.
package types

// Tier mirrors contracts.ActionTier in contracts/schemas.py.
//
// Mapping (Python → Go):
//   T0_SANDBOX      → TierSandbox      (reversible, sandbox only)
//   T1_APPROVAL     → TierSafe         (reversible, requires approval)
//   T2_HIGH_RISK    → TierReversible   (irreversible, requires approval + ticket)
//   T3_BLOCKED      → TierDestructive  (structurally unreachable)
type Tier string

const (
	TierSandbox     Tier = "T0_SANDBOX"
	TierSafe        Tier = "T1_SAFE"
	TierReversible  Tier = "T2_REVERSIBLE"
	TierDestructive Tier = "T3_DESTRUCTIVE"
	TierHighRisk    Tier = "T2_HIGH_RISK" // alias for TierReversible
)

// Decision is the broker's verdict on a proposal.
type Decision string

const (
	DecisionAllowSandbox    Decision = "ALLOW_SANDBOX"
	DecisionRequireApproval Decision = "REQUIRE_APPROVAL"
	DecisionBlocked         Decision = "BLOCKED"
)

// Proposal is the broker-side view of an incoming ActionProposal.
type Proposal struct {
	ProposalID string
	ActionType string
	Tier       Tier
	Version    int
}

// Definition is one entry in the action registry.
type Definition struct {
	ActionType  string
	Version     int
	Tier        Tier
	Sandboxable bool
	Owner       string
}