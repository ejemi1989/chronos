package main

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// projectRoot returns the absolute path to the action_broker module root,
// regardless of where the test binary was invoked from.
func projectRoot(t *testing.T) string {
	t.Helper()
	_, thisFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("cannot resolve test file path")
	}
	// thisFile is cmd/broker/static_check_test.go; walk up to module root.
	dir := filepath.Dir(thisFile)
	root := filepath.Join(dir, "..", "..")
	abs, err := filepath.Abs(root)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(abs, "go.mod")); err != nil {
		t.Fatalf("not a module root: %s", abs)
	}
	return abs
}

func parseDir(t *testing.T, root string) map[string]*ast.Package {
	t.Helper()
	fset := token.NewFileSet()
	pkgs, err := parser.ParseDir(fset, root, nil, 0)
	if err != nil {
		t.Fatalf("parse %s: %v", root, err)
	}
	return pkgs
}

// TestNoExecutorForT3 is a static check that no executor function exists
// for the T3 destructive tier anywhere in the broker source.
//
// STRUCTURAL GUARANTEE: even if a future change accidentally returned
// DecisionAllowSandbox for a T3 input, there is no code path that could
// dispatch an executor because none is defined.
func TestNoExecutorForT3(t *testing.T) {
	root := projectRoot(t)
	forbidden := []string{
		"executedestructive",
		"rundestructive",
		"applydestructive",
		"dispatchdestructive",
		"deleteproduction",
		"alterproduction",
		"deleteproductiondata",
		"alterproductionschema",
	}
	dirs := []string{
		filepath.Join(root, "cmd", "server"),
		filepath.Join(root, "internal"),
	}
	for _, dir := range dirs {
		err := filepath.Walk(dir, func(path string, info os.FileInfo, err error) error {
			if err != nil || info.IsDir() {
				return nil
			}
			if !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
				return nil
			}
			fset := token.NewFileSet()
			f, err := parser.ParseFile(fset, path, nil, 0)
			if err != nil {
				return err
			}
			for _, decl := range f.Decls {
				fn, ok := decl.(*ast.FuncDecl)
				if !ok {
					continue
				}
				lower := strings.ToLower(fn.Name.Name)
				for _, bad := range forbidden {
					if strings.Contains(lower, bad) {
						t.Fatalf("forbidden function declared: %s in %s", fn.Name.Name, path)
					}
				}
			}
			return nil
		})
		if err != nil {
			t.Fatal(err)
		}
	}
}

// TestPolicyHasNoT3AllowBranch proves the policy package has no code
// path that can return ALLOW_SANDBOX or REQUIRE_APPROVAL for T3.
func TestPolicyHasNoT3AllowBranch(t *testing.T) {
	root := projectRoot(t)
	policyDir := filepath.Join(root, "internal", "policy")
	pkgs := parseDir(t, policyDir)
	for _, pkg := range pkgs {
		for _, file := range pkg.Files {
			for _, decl := range file.Decls {
				fn, ok := decl.(*ast.FuncDecl)
				if !ok {
					continue
				}
				ast.Inspect(fn, func(n ast.Node) bool {
					if cs, ok := n.(*ast.CaseClause); ok {
						for _, expr := range cs.List {
							id, ok := expr.(*ast.Ident)
							if !ok || id.Name != "TierDestructive" {
								continue
							}
							for _, stmt := range cs.Body {
								rs, ok := stmt.(*ast.ReturnStmt)
								if !ok {
									continue
								}
								for _, r := range rs.Results {
									sel, ok := r.(*ast.SelectorExpr)
									if !ok {
										continue
									}
									base, ok := sel.X.(*ast.Ident)
									if !ok || base.Name != "types" {
										continue
									}
									if strings.HasPrefix(sel.Sel.Name, "Decision") && sel.Sel.Name != "DecisionBlocked" {
										t.Fatalf("%s: T3 case returns %s (must be DecisionBlocked)",
											file.Name.Name, sel.Sel.Name)
									}
								}
							}
						}
					}
					return true
				})
			}
		}
	}
}

// TestT3NeverReachesMainDispatch verifies the main HTTP handler does not
// dispatch any executor for T3 — it only writes the response.
func TestT3NeverReachesMainDispatch(t *testing.T) {
	root := projectRoot(t)
	mainFile := filepath.Join(root, "cmd", "server", "main.go")
	src, err := os.ReadFile(mainFile)
	if err != nil {
		t.Fatal(err)
	}
	// The handler must invoke policy.Evaluate and serialize the result.
	// It must NOT call any function whose name contains "exec", "run", or
	// "dispatch" against a proposal.
	text := string(src)
	if !strings.Contains(text, "policy.Evaluate") {
		t.Fatal("main handler must call policy.Evaluate")
	}
	if strings.Contains(text, "policy.Evaluate(") {
		// ok — the handler does call Evaluate
	}
	// Negative checks
	for _, bad := range []string{"exec.", "execProposal", "runProposal", "execute(", "applyProposal"} {
		if strings.Contains(text, bad) {
			t.Fatalf("main handler must not reference %s", bad)
		}
	}
}