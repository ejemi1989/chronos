package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"

	"github.com/chronos/action-broker-go/internal/registry"
)

// makeTestJWT returns an HS256 token signed with "test-key" that the
// handler's stub keyfunc will accept.
func makeTestJWT() string {
	claims := jwt.MapClaims{
		"sub":    "orchestrator",
		"scopes": []any{"chronos.broker"},
		"exp":    time.Now().Add(time.Hour).Unix(),
	}
	tok := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	s, _ := tok.SignedString([]byte("test-key"))
	return s
}

func post(srv *httptest.Server, body any) (*http.Response, error) {
	raw, _ := json.Marshal(body)
	req, _ := http.NewRequest(http.MethodPost, srv.URL, bytes.NewReader(raw))
	req.Header.Set("Authorization", "Bearer "+makeTestJWT())
	req.Header.Set("Content-Type", "application/json")
	return http.DefaultClient.Do(req)
}

// keep base64 import used (referenced for ad-hoc tokens)
var _ = base64.URLEncoding

func TestHTTPInvoke_T3IsStructurallyBlocked(t *testing.T) {
	reg := registry.Load(defaultRegistry())
	srv := httptest.NewServer(makeInvokeHandler(reg))
	defer srv.Close()

	resp, err := post(srv, InvokeRequest{
		ProposalID: "p-evil",
		ActionType: "db.drop",
		Tier:       "T3_DESTRUCTIVE",
		Version:    1,
	})
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()

	var out InvokeResponse
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		t.Fatal(err)
	}
	if out.Decision != "BLOCKED" {
		t.Fatalf("expected BLOCKED, got %s", out.Decision)
	}
	if !strings.Contains(out.Reason, "T3") {
		t.Fatalf("reason should mention T3: %s", out.Reason)
	}
}

func TestHTTPInvoke_T1AllowSandbox(t *testing.T) {
	reg := registry.Load(defaultRegistry())
	srv := httptest.NewServer(makeInvokeHandler(reg))
	defer srv.Close()

	resp, err := post(srv, InvokeRequest{
		ProposalID: "p1",
		ActionType: "cache.flush",
		Tier:       "T1_SAFE",
		Version:    1,
	})
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var out InvokeResponse
	_ = json.NewDecoder(resp.Body).Decode(&out)
	if out.Decision != "ALLOW_SANDBOX" {
		t.Fatalf("expected ALLOW_SANDBOX, got %s (reason=%s)", out.Decision, out.Reason)
	}
}

func TestHTTPInvoke_RejectsUnauthorized(t *testing.T) {
	reg := registry.Load(defaultRegistry())
	srv := httptest.NewServer(makeInvokeHandler(reg))
	defer srv.Close()

	raw, _ := json.Marshal(InvokeRequest{ProposalID: "p1", ActionType: "cache.flush", Tier: "T1_SAFE", Version: 1})
	req, _ := http.NewRequest(http.MethodPost, srv.URL, bytes.NewReader(raw))
	// no auth header
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", resp.StatusCode)
	}
}