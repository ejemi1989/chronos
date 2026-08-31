package auth

import (
	"testing"

	"github.com/golang-jwt/jwt/v5"
)

func TestVerify_RejectsMissingHeader(t *testing.T) {
	if _, err := Verify("", func(t *jwt.Token) (any, error) { return nil, nil }); err == nil {
		t.Fatal("expected error on empty header")
	}
}

func TestVerify_RejectsWrongScheme(t *testing.T) {
	if _, err := Verify("Basic abc", func(t *jwt.Token) (any, error) { return nil, nil }); err == nil {
		t.Fatal("expected error on non-Bearer scheme")
	}
}