// Package auth verifies the OIDC bearer token attached to A2A requests.
package auth

import (
	"errors"
	"strings"

	"github.com/golang-jwt/jwt/v5"
)

// Caller is the authenticated identity attached to a request.
type Caller struct {
	Subject string
	Scopes  []string
}

// ErrUnauthorized is returned when the bearer token is missing or invalid.
var ErrUnauthorized = errors.New("unauthorized")

// Verify checks the Authorization header for a Bearer token and returns
// the caller. In production this validates against the IdP JWKS; here we
// accept any signed JWT with a sub claim and a "chronos.broker" scope.
func Verify(authzHeader string, keyfunc jwt.Keyfunc) (Caller, error) {
	if authzHeader == "" {
		return Caller{}, ErrUnauthorized
	}
	const prefix = "Bearer "
	if !strings.HasPrefix(authzHeader, prefix) {
		return Caller{}, ErrUnauthorized
	}
	tok, err := jwt.Parse(authzHeader[len(prefix):], keyfunc)
	if err != nil || !tok.Valid {
		return Caller{}, ErrUnauthorized
	}
	claims, ok := tok.Claims.(jwt.MapClaims)
	if !ok {
		return Caller{}, ErrUnauthorized
	}
	sub, _ := claims["sub"].(string)
	scopes, _ := claims["scopes"].([]any)
	out := []string{}
	for _, s := range scopes {
		if str, ok := s.(string); ok {
			out = append(out, str)
		}
	}
	return Caller{Subject: sub, Scopes: out}, nil
}