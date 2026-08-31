// Package policy implements the deterministic decision policy for the
// Chronos Action Broker.
//
// KEY DESIGN PROPERTY: T3_DESTRUCTIVE actions are STRUCTURALLY unreachable
// from any executor path. Evaluate() returns DecisionBlocked for any T3
// input; no code in this package or downstream packages can override that.
package policy

import (
	"fmt"

	"github.com/chronos/action-broker-go/internal/types"
)

// Evaluate returns the deterministic decision.
//
// CONTRACT:
//   - T3_DESTRUCTIVE   → BLOCKED (always; no override)
//   - unknown version  → BLOCKED
//   - not in registry  → BLOCKED
//   - tier mismatch    → BLOCKED
//   - T0_SANDBOX       → ALLOW_SANDBOX (only if registry.Sandboxable)
//   - T1_SAFE          → ALLOW_SANDBOX (only if registry.Sandboxable)
//   - T2_REVERSIBLE    → REQUIRE_APPROVAL
//   - T2_HIGH_RISK     → REQUIRE_APPROVAL
func Evaluate(p types.Proposal, def types.Definition, present bool) (types.Decision, string) {
	if p.Tier == types.TierDestructive {
		// STRUCTURAL: this branch has no caller. T3 is the only path that
		// returns BLOCKED with no executor dispatch. The static check test
		// enforces this — see cmd/server/static_check_test.go.
		return types.DecisionBlocked, "T3_DESTRUCTIVE structurally blocked"
	}

	if !present {
		return types.DecisionBlocked, fmt.Sprintf("unknown action %s@%d", p.ActionType, p.Version)
	}
	if def.Tier != p.Tier {
		return types.DecisionBlocked, fmt.Sprintf("tier mismatch: proposal=%s registry=%s", p.Tier, def.Tier)
	}

	switch p.Tier {
	case types.TierSandbox:
		if !def.Sandboxable {
			return types.DecisionBlocked, "T0 action not sandboxable per registry"
		}
		return types.DecisionAllowSandbox, "T0 sandboxed"
	case types.TierSafe:
		if !def.Sandboxable {
			return types.DecisionBlocked, "T1 action not sandboxable per registry"
		}
		return types.DecisionAllowSandbox, "T1 sandboxed"
	case types.TierReversible, types.TierHighRisk:
		return types.DecisionRequireApproval, "T2 requires human approval"
	default:
		// Unreachable: TierDestructive already returned above.
		return types.DecisionBlocked, "unreachable tier"
	}
}