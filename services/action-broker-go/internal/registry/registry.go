// Package registry holds the versioned, signed allow-list of action types.
package registry

import (
	"strconv"
	"sync"

	"github.com/chronos/action-broker-go/internal/types"
)

// Registry is an immutable snapshot loaded at startup.
type Registry struct {
	mu      sync.RWMutex
	byKey   map[string]types.Definition
	version int
}

// Load constructs a registry from a slice of definitions.
func Load(defs []types.Definition) *Registry {
	r := &Registry{byKey: map[string]types.Definition{}, version: 1}
	for _, d := range defs {
		r.byKey[fmtKey(d.ActionType, d.Version)] = d
	}
	return r
}

func fmtKey(action string, v int) string { return action + "@" + strconv.Itoa(v) }

// Lookup returns the definition for an (action, version) pair.
func (r *Registry) Lookup(action string, version int) (types.Definition, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	d, ok := r.byKey[fmtKey(action, version)]
	return d, ok
}

// Version returns the registry version.
func (r *Registry) Version() int { return r.version }