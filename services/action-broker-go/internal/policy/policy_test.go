package policy

import (
	"testing"

	"github.com/chronos/action-broker-go/internal/types"
)

func TestEvaluate_T3IsStructurallyBlocked(t *testing.T) {
	// Even with no registry and a permissive def, T3 must be blocked.
	d, reason := Evaluate(
		types.Proposal{Tier: types.TierDestructive},
		types.Definition{},
		false,
	)
	if d != types.DecisionBlocked {
		t.Fatalf("T3 must always be BLOCKED, got %s", d)
	}
	if reason == "" {
		t.Fatal("reason required")
	}
}

func TestEvaluate_T1SandboxedAllows(t *testing.T) {
	d, _ := Evaluate(
		types.Proposal{Tier: types.TierSafe, ActionType: "cache.flush", Version: 1},
		types.Definition{Tier: types.TierSafe, Sandboxable: true},
		true,
	)
	if d != types.DecisionAllowSandbox {
		t.Fatalf("expected ALLOW_SANDBOX, got %s", d)
	}
}

func TestEvaluate_T2RequiresApproval(t *testing.T) {
	d, _ := Evaluate(
		types.Proposal{Tier: types.TierReversible, ActionType: "queue.drain", Version: 1},
		types.Definition{Tier: types.TierReversible},
		true,
	)
	if d != types.DecisionRequireApproval {
		t.Fatalf("expected REQUIRE_APPROVAL, got %s", d)
	}
}

func TestEvaluate_UnknownActionBlocked(t *testing.T) {
	d, _ := Evaluate(
		types.Proposal{Tier: types.TierSafe, ActionType: "nope", Version: 1},
		types.Definition{},
		false,
	)
	if d != types.DecisionBlocked {
		t.Fatalf("expected BLOCKED, got %s", d)
	}
}

func TestEvaluate_TierMismatchBlocked(t *testing.T) {
	d, _ := Evaluate(
		types.Proposal{Tier: types.TierSafe, ActionType: "x", Version: 1},
		types.Definition{Tier: types.TierReversible},
		true,
	)
	if d != types.DecisionBlocked {
		t.Fatalf("expected BLOCKED on tier mismatch, got %s", d)
	}
}