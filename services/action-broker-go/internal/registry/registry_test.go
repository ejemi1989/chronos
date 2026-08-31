package registry

import (
	"testing"

	"github.com/chronos/action-broker-go/internal/types"
)

func TestRegistry_LookupAndMiss(t *testing.T) {
	r := Load([]types.Definition{
		{ActionType: "cache.flush", Version: 1, Tier: types.TierSafe, Sandboxable: true},
	})
	if _, ok := r.Lookup("cache.flush", 1); !ok {
		t.Fatal("expected hit")
	}
	if _, ok := r.Lookup("cache.flush", 99); ok {
		t.Fatal("expected miss")
	}
}