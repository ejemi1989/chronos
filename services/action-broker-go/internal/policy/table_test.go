package policy

import (
	"strings"
	"testing"

	"github.com/chronos/action-broker-go/internal/types"
)

// TestEvaluate_TableDriven covers the full decision matrix.
func TestEvaluate_TableDriven(t *testing.T) {
	cases := []struct {
		name       string
		tier       types.Tier
		action     string
		version    int
		def        types.Definition
		present    bool
		wantStatus types.Decision
		wantReason string
	}{
		{
			name:       "T0 sandbox → ALLOW",
			tier:       types.TierSandbox,
			action:     "cache.flush",
			version:    1,
			def:        types.Definition{Tier: types.TierSandbox, Sandboxable: true},
			present:    true,
			wantStatus: types.DecisionAllowSandbox,
		},
		{
			name:       "T1 safe sandboxable → ALLOW",
			tier:       types.TierSafe,
			action:     "cache.flush",
			version:    1,
			def:        types.Definition{Tier: types.TierSafe, Sandboxable: true},
			present:    true,
			wantStatus: types.DecisionAllowSandbox,
		},
		{
			name:       "T1 safe not sandboxable → BLOCKED",
			tier:       types.TierSafe,
			action:     "weird.flush",
			version:    1,
			def:        types.Definition{Tier: types.TierSafe, Sandboxable: false},
			present:    true,
			wantStatus: types.DecisionBlocked,
			wantReason: "sandboxable",
		},
		{
			name:       "T2 reversible → REQUIRE_APPROVAL",
			tier:       types.TierReversible,
			action:     "queue.drain",
			version:    1,
			def:        types.Definition{Tier: types.TierReversible},
			present:    true,
			wantStatus: types.DecisionRequireApproval,
		},
		{
			name:       "T2 high risk → REQUIRE_APPROVAL",
			tier:       types.TierHighRisk,
			action:     "schema.migrate",
			version:    1,
			def:        types.Definition{Tier: types.TierHighRisk},
			present:    true,
			wantStatus: types.DecisionRequireApproval,
		},
		{
			name:       "T3 destructive → BLOCKED even if sandboxable",
			tier:       types.TierDestructive,
			action:     "db.drop",
			version:    1,
			def:        types.Definition{Tier: types.TierDestructive, Sandboxable: true},
			present:    true,
			wantStatus: types.DecisionBlocked,
			wantReason: "T3_DESTRUCTIVE",
		},
		{
			name:       "Unknown action → BLOCKED",
			tier:       types.TierSafe,
			action:     "rogue.execute",
			version:    1,
			def:        types.Definition{},
			present:    false,
			wantStatus: types.DecisionBlocked,
			wantReason: "unknown action",
		},
		{
			name:       "Tier mismatch → BLOCKED",
			tier:       types.TierSafe,
			action:     "queue.drain",
			version:    1,
			def:        types.Definition{Tier: types.TierReversible},
			present:    true,
			wantStatus: types.DecisionBlocked,
			wantReason: "tier mismatch",
		},
		{
			name:       "Unknown version → BLOCKED",
			tier:       types.TierSafe,
			action:     "cache.flush",
			version:    99,
			def:        types.Definition{Tier: types.TierSafe, Sandboxable: true},
			present:    false,
			wantStatus: types.DecisionBlocked,
			wantReason: "unknown action",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			d, reason := Evaluate(
				types.Proposal{Tier: tc.tier, ActionType: tc.action, Version: tc.version},
				tc.def,
				tc.present,
			)
			if d != tc.wantStatus {
				t.Fatalf("decision: want %s got %s (reason=%s)", tc.wantStatus, d, reason)
			}
			if tc.wantReason != "" && !strings.Contains(reason, tc.wantReason) {
				t.Fatalf("reason: want substring %q got %q", tc.wantReason, reason)
			}
		})
	}
}

// TestEvaluate_FuzzRandomTiers — random inputs never produce a decision
// other than BLOCKED for T3 regardless of registry contents.
func TestEvaluate_FuzzRandomTiers(t *testing.T) {
	tiers := []types.Tier{
		types.TierSandbox, types.TierSafe,
		types.TierReversible, types.TierHighRisk, types.TierDestructive,
	}
	for _, tier := range tiers {
		for i := 0; i < 50; i++ {
			d, _ := Evaluate(
				types.Proposal{Tier: tier, ActionType: "x", Version: i},
				types.Definition{Tier: tier, Sandboxable: true},
				true,
			)
			if tier == types.TierDestructive && d != types.DecisionBlocked {
				t.Fatalf("tier %s must block, got %s", tier, d)
			}
		}
	}
}