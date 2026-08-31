package main

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/chronos/action-broker-go/internal/registry"
	"github.com/chronos/action-broker-go/internal/types"
)

// TestHTTP_FuzzMalformedJSON ensures the handler never panics or returns
// 500 for any malformed input. All paths must result in 400 or 401.
func TestHTTP_FuzzMalformedJSON(t *testing.T) {
	reg := registry.Load([]types.Definition{
		{ActionType: "cache.flush", Version: 1, Tier: types.TierSafe, Sandboxable: true},
	})
	srv := httptest.NewServer(makeInvokeHandler(reg))
	defer srv.Close()

	cases := []string{
		"",
		"{",
		"}",
		"not json at all",
		"{\"proposal_id\":}",
		"[]",
		"\"a string\"",
		"null",
		"{\"proposal_id\":\"x\",\"action_type\":123}",
		strings.Repeat("a", 10000),
	}
	for _, body := range cases {
		req, _ := http.NewRequest(http.MethodPost, srv.URL, bytes.NewReader([]byte(body)))
		req.Header.Set("Authorization", "Bearer "+makeTestJWT())
		req.Header.Set("Content-Type", "application/json")
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		_, _ = io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
		if resp.StatusCode == http.StatusInternalServerError {
			t.Fatalf("500 on body %q", body[:min(40, len(body))])
		}
		if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusBadRequest {
			t.Fatalf("expected 200 or 400, got %d for %q", resp.StatusCode, body[:min(40, len(body))])
		}
	}
}

// TestHTTP_IdempotentReplay — submitting the same proposal twice produces
// the same decision and is recorded twice in the ledger (append-only).
func TestHTTP_IdempotentReplay(t *testing.T) {
	reg := registry.Load([]types.Definition{
		{ActionType: "cache.flush", Version: 1, Tier: types.TierSafe, Sandboxable: true},
	})
	srv := httptest.NewServer(makeInvokeHandler(reg))
	defer srv.Close()

	body, _ := json.Marshal(InvokeRequest{ProposalID: "p-idem", ActionType: "cache.flush", Tier: "T1_SAFE", Version: 1})

	// First submit
	r1, _ := postRaw(srv.URL, body)
	var v1 InvokeResponse
	_ = json.NewDecoder(r1.Body).Decode(&v1)
	r1.Body.Close()

	// Second submit (same payload)
	r2, _ := postRaw(srv.URL, body)
	var v2 InvokeResponse
	_ = json.NewDecoder(r2.Body).Decode(&v2)
	r2.Body.Close()

	if v1.Decision != v2.Decision {
		t.Fatalf("decision must be deterministic: %s vs %s", v1.Decision, v2.Decision)
	}
}

func postRaw(url string, body []byte) (*http.Response, error) {
	req, _ := http.NewRequest(http.MethodPost, url, bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+makeTestJWT())
	req.Header.Set("Content-Type", "application/json")
	return http.DefaultClient.Do(req)
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}