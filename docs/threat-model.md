# Chronos — Threat model

Each risk maps to (1) a test that proves the mitigation and (2) an
implementation control. Format: STRIDE — *Spoofing, Tampering, Repudiation,
Information disclosure, Denial of service, Elevation of privilege*.

## Risks and controls

| # | STRIDE   | Risk                                          | Control                                                                                       | Test                                                            |
|---|----------|-----------------------------------------------|------------------------------------------------------------------------------------------------|-----------------------------------------------------------------|
| 1 | S, T, E  | **Prompt injection** in incident telemetry    | Pydantic schema rejects unknown fields, length limits, pattern-restricted IDs.                | `tests/test_contracts.py::test_incident_rejects_extra`            |
| 2 | S, T     | **Tool poisoning** — model calls an exec tool | Agents have NO tools attached. Controller verifies tool list at startup.                      | `agents/{detection,proposer,auditor}.py` (no `tools=[...]`)      |
| 3 | T, E     | **Confused deputy** — broker called by anyone | OIDC bearer + JWKS validation in broker; orchestrator mints short-lived (5m) tokens.           | `cmd/server/main_test.go::TestHTTPInvoke_RejectsUnauthorized`    |
| 4 | T, R     | **Replay attacks** on broker                  | Tokens carry `jti` + `exp`; A2A endpoint requires fresh token per request.                     | `cmd/server/fuzz_test.go::TestHTTP_IdempotentReplay`              |
| 5 | E        | **Privilege escalation** via Tier inflation  | Tier is derived by the controller from structural properties — never from model output.       | `tests/test_controller.py::test_derive_tier_*`                  |
| 6 | T, E     | **Forced destructive action**                 | DELETE_DATA / ALTER_PRODUCTION_SCHEMA forbidden at Pydantic enum + JSON Schema + broker policy. | `cmd/server/static_check_test.go::TestNoExecutorForT3`           |
| 7 | I, R     | **Data leakage** via error messages           | Broker responses include only `reason`, never internal state. Reason is a fixed string.        | `internal/policy/policy_test.go::TestEvaluate_*`                 |
| 8 | S, T     | **SSRF** via target URL                       | Target must match `^[a-z][a-z0-9._-]{1,63}$`; broker never fetches URLs.                       | `tests/test_contracts.py::test_proposal_rejects_bad_target`       |
| 9 | I        | **Credential exposure** in logs               | Orchestrator redacts `Authorization` headers before logging. Logger is configured to drop.    | Manual review + log scan in CI.                                  |
| 10| D        | **Denial of service** via giant payloads      | Pydantic field length caps (e.g. `error_log` ≤ 65536); broker request size cap (1 MiB).        | `tests/test_contracts.py` (length limits)                         |
| 11| T, R     | **Audit tampering** in ledger                | Hash chain + `verify_chain()`; Firestore rules deny `update`/`delete`; entries immutable.     | `tests/test_ledger.py::test_verify_chain_detects_tamper`          |
| 12| T        | **Schema confusion** — wrong-tier proposal    | Broker checks `def.Tier != p.Tier` and BLOCKS on mismatch.                                     | `internal/policy/table_test.go::TestEvaluate_TableDriven`         |
| 13| E        | **Privilege escalation** via approval grant   | Approval is gated by a human; the orchestrator never auto-grants. Approval is a separate IAM role. | `infra/iam.md`                                                |
| 14| S, R     | **Forged audit trail**                        | Every entry carries `previous_hash`; gaps are detected by `verify_chain`.                     | `tests/test_ledger.py::test_concurrent_writers_no_duplicate_seq` |

## Trust model (tamper-evident, not immutable)

> Chronos is tamper-evident under the stated trust model — anyone with
> Firestore admin access can rewrite the chain, but doing so breaks
> `verify_chain()`. The system is **not** absolutely immutable; it provides
> strong evidence of tampering that auditors can act on.

## Fail-closed behavior

Every error path in the orchestrator terminates in `BLOCKED` with the run
persisted as terminal. The broker's `evaluate` always returns one of three
enum values — never panics, never returns 500. The static check test
guarantees no executor exists for T3 even if a future code change attempted
to introduce one.

## Correlation IDs

Every `WorkflowRun` carries `run_id`. Every Pub/Sub message includes
`incident_id` and (when present) `run_id`. Logs use the same identifiers
so a single grep can rebuild a timeline.

## Rate limits

The broker accepts at most one request per goroutine per connection. The
orchestrator's FastAPI app uses uvicorn's default `--limit-concurrency`
of 1000. The Pub/Sub subscription's ack deadline of 60 s caps tail latency.

## Out of scope

- Side-channel attacks against Vertex AI.
- GCP service-account theft (mitigated by workload identity + IAM roles).
- Physical access to Cloud Run regions.