// Server is the A2A HTTP entrypoint for the Chronos Action Broker.
//
// It exposes:
//   GET  /healthz                — liveness probe
//   GET  /.well-known/agent.json — A2A agent card
//   POST /a2a/v1/invoke          — submit an ActionProposal for evaluation
//   GET  /ledger/recent          — recent ledger entries (dashboard)
//   GET  /                       — dashboard HTML
package main

import (
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"

	"github.com/chronos/action-broker-go/internal/auth"
	"github.com/chronos/action-broker-go/internal/policy"
	"github.com/chronos/action-broker-go/internal/registry"
	"github.com/chronos/action-broker-go/internal/server"
	"github.com/chronos/action-broker-go/internal/types"
)

func itoa(i int) string { return strconv.Itoa(i) }
func nowUnix() int64    { return time.Now().Unix() }

// memLedger is an in-process append-only log used by the dashboard.
// In production this is replaced by the Firestore ledger with the
// transaction-safe append path. The in-memory version preserves the same
// hash-chain invariants so the dashboard can run without GCP.
type memEntry struct {
	Seq         int    `json:"seq"`
	Timestamp   int64  `json:"timestamp"`
	Actor       string `json:"actor"`
	ActionType  string `json:"action_type"`
	ProposalID  string `json:"proposal_id"`
	Decision    string `json:"decision"`
	EntryHash   string `json:"entry_hash"`
	PreviousHash string `json:"previous_hash"`
}

var (
	memMu      sync.Mutex
	memLog     []memEntry
	memTraces  []traceEntry
	canonical  = func(e memEntry) string { return e.Actor + "|" + e.ActionType + "|" + e.ProposalID + "|" + e.Decision + "|" + e.EntryHash }
	traceMu    sync.Mutex
)

type traceEntry struct {
	TraceID    string         `json:"trace_id"`
	Name       string         `json:"name"`
	Status     string         `json:"status"`
	DurationMS float64        `json:"duration_ms"`
	Service    string         `json:"service"`
	Attributes map[string]any `json:"attributes"`
	Timestamp  int64          `json:"timestamp"`
}

func recordTrace(t traceEntry) {
	traceMu.Lock()
	defer traceMu.Unlock()
	memTraces = append(memTraces, t)
	if len(memTraces) > 500 {
		memTraces = memTraces[len(memTraces)-500:]
	}
}

func recentTraces() []traceEntry {
	traceMu.Lock()
	defer traceMu.Unlock()
	out := make([]traceEntry, len(memTraces))
	copy(out, memTraces)
	sort.Slice(out, func(i, j int) bool { return out[i].Timestamp > out[j].Timestamp })
	return out
}

func appendMem(actor, actionType, proposalID, decision string) memEntry {
	memMu.Lock()
	defer memMu.Unlock()
	prevHash := ""
	seq := 0
	if n := len(memLog); n > 0 {
		prevHash = memLog[n-1].EntryHash
		seq = memLog[n-1].Seq + 1
	}
	h := sha256.Sum256([]byte(prevHash + "|" + actor + "|" + actionType + "|" + proposalID + "|" + decision + "|" + itoa(seq)))
	e := memEntry{
		Seq:          seq,
		Timestamp:    nowUnix(),
		Actor:        actor,
		ActionType:   actionType,
		ProposalID:   proposalID,
		Decision:     decision,
		EntryHash:    hex.EncodeToString(h[:]),
		PreviousHash: prevHash,
	}
	memLog = append(memLog, e)
	return e
}

func recentMem() []memEntry {
	memMu.Lock()
	defer memMu.Unlock()
	out := make([]memEntry, len(memLog))
	copy(out, memLog)
	sort.Slice(out, func(i, j int) bool { return out[i].Seq > out[j].Seq })
	if len(out) > 12 {
		out = out[:12]
	}
	return out
}

func main() {
	reg := registry.Load(defaultRegistry())
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		log.Printf("GET /healthz from=%s ua=%q", r.RemoteAddr, r.UserAgent())
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})
	mux.HandleFunc("/.well-known/agent.json", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(agentCard())
	})
	mux.HandleFunc("/a2a/v1/invoke", makeInvokeHandler(reg))
	mux.HandleFunc("/ledger/recent", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(recentMem())
	})
	mux.HandleFunc("/traces/recent", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(recentTraces())
	})
	mux.HandleFunc("/", serveDashboard)

	srv := server.New(mux)
	addr := os.Getenv("CHRONOS_BROKER_ADDR")
	if addr == "" {
		addr = ":8080"
	}
	log.Println("chronos action broker listening " + addr)
	if err := srv.ListenAndServe(addr); err != nil {
		log.Fatal(err)
	}
}

//go:embed assets/index.html
var dashboardHTML []byte

func serveDashboard(w http.ResponseWriter, r *http.Request) {
	// Root path and /healthz return "ok" so liveness probes work.
	if r.URL.Path == "/healthz" {
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok\n"))
		return
	}
	// Root path serves the embedded dashboard.
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Cache-Control", "no-cache")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(dashboardHTML)
}

func agentCard() map[string]any {
	return map[string]any{
		"name":        "chronos-action-broker",
		"version":     "1.0.0",
		"description": "Governed incident-remediation broker. T3 destructive actions are structurally blocked.",
		"capabilities": map[string]any{
			"propose_action":   true,
			"execute_action":   true,
			"sandbox":          true,
			"human_approval":   true,
			"block_destructive": true,
		},
		"endpoints": map[string]string{
			"invoke": "/a2a/v1/invoke",
			"health": "/healthz",
		},
	}
}

type InvokeRequest struct {
	ProposalID string `json:"proposal_id"`
	ActionType string `json:"action_type"`
	Tier       string `json:"tier"`
	Version    int    `json:"version"`
}

type InvokeResponse struct {
	ProposalID string `json:"proposal_id"`
	Decision   string `json:"decision"`
	Reason     string `json:"reason"`
}

func makeInvokeHandler(reg *registry.Registry) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		spanID := newSpanID()

		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		_, err := auth.Verify(r.Header.Get("Authorization"), func(_ *jwt.Token) (any, error) {
			return []byte("test-key"), nil
		})
		if err != nil {
			emitTrace(spanID, "broker.invoke", "ERROR", start, map[string]any{"reason": "unauthorized"})
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		var req InvokeRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			emitTrace(spanID, "broker.invoke", "ERROR", start, map[string]any{"reason": "bad_json"})
			http.Error(w, "bad json", http.StatusBadRequest)
			return
		}
		def, present := reg.Lookup(req.ActionType, req.Version)
		decision, reason := policy.Evaluate(
			types.Proposal{
				ProposalID: req.ProposalID,
				ActionType: req.ActionType,
				Tier:       types.Tier(req.Tier),
				Version:    req.Version,
			},
			def,
			present,
		)
		appendMem("orchestrator", req.ActionType, req.ProposalID, string(decision))
		emitTrace(spanID, "broker.invoke", "OK", start, map[string]any{
			"proposal_id": req.ProposalID,
			"action_type": req.ActionType,
			"tier":        req.Tier,
			"decision":    string(decision),
			"reason":      reason,
		})
		_ = json.NewEncoder(w).Encode(InvokeResponse{
			ProposalID: req.ProposalID,
			Decision:   string(decision),
			Reason:     reason,
		})
	}
}

func newSpanID() string {
	return strings.ReplaceAll(uuid.NewString(), "-", "")[:16]
}

func emitTrace(spanID, name, status string, start time.Time, attrs map[string]any) {
	dur := time.Since(start)
	recordTrace(traceEntry{
		TraceID:    spanID,
		Name:       name,
		Status:     status,
		DurationMS: float64(dur.Microseconds()) / 1000.0,
		Service:    "chronos-action-broker",
		Attributes: attrs,
		Timestamp:  nowUnix(),
	})
	line, _ := json.Marshal(map[string]any{
		"trace_id":    spanID,
		"name":        name,
		"status":      status,
		"duration_ms": float64(dur.Microseconds()) / 1000.0,
		"attributes":  attrs,
		"service":     "chronos-action-broker",
	})
	log.Printf("trace %s", line)
}

func defaultRegistry() []types.Definition {
	return []types.Definition{
		{ActionType: "cache.flush", Version: 1, Tier: types.TierSafe, Sandboxable: true, Owner: "platform"},
		{ActionType: "queue.drain", Version: 1, Tier: types.TierReversible, Sandboxable: false, Owner: "platform"},
		{ActionType: "db.vacuum", Version: 1, Tier: types.TierReversible, Sandboxable: false, Owner: "data"},
		{ActionType: "schema.migrate", Version: 1, Tier: types.TierHighRisk, Sandboxable: false, Owner: "data"},
	}
}
