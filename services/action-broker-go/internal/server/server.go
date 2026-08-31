// Package server is a thin facade over net/http that the A2A SDK exposes.
// We declare a local type so the package compiles standalone without the
// external SDK; the real implementation swaps in the SDK server.
package server

import "net/http"

type Server struct{ h http.Handler }

func New(h http.Handler) *Server { return &Server{h: h} }
func (s *Server) ListenAndServe(addr string) error {
	srv := &http.Server{Addr: addr, Handler: s.h}
	return srv.ListenAndServe()
}
func (s *Server) Handler() http.Handler { return s.h }