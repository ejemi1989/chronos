# Chronos — 4-minute demo script

## Setup (60 s)

```
make install
make broker &         # Go A2A broker on :8080
make orchestrator &   # FastAPI on :8080 (api under /api)
```

Open `http://localhost:8080/` (HTML dashboard) and
`http://localhost:8501/` (Streamlit dashboard) in two tabs.

## Beat 1 — Detection (45 s)

```bash
curl -s -X POST http://localhost:8080/api/incidents \
  -H "Content-Type: application/json" \
  -d @fixtures/incidents/schema-drift.json | jq
```

Walk through:

1. **DetectionAgent** classifies the log → `SCHEMA_CHANGE` (HIGH).
2. State machine: `RECEIVED → CLASSIFIED → DEBATING → PROPOSED → POLICY_REVIEW → ALLOW_SANDBOX → EXECUTING → VERIFIED → CLOSED`.
3. Tier derived from `reversible=true, financial_impact=0` → `T0_SANDBOX`.
4. Synthetic proposal: `ROLLBACK_SCHEMA` on `prod.users001`.

## Beat 2 — Reversible approval gate (45 s)

```bash
curl -s -X POST http://localhost:8080/api/incidents \
  -H "Content-Type: application/json" \
  -d '{
    "incident_id":"inc_zzzzzz",
    "pipeline_id":"pipe_pay001",
    "error_log":"upstream API timed out after 30000ms deadline exceeded",
    "context":{},"detected_at":1.0
  }' | jq
```

Walk through:

1. Classified as `API_TIMEOUT` (MEDIUM).
2. Heuristic maps to `REPLAY_BATCH` → still safe (reversible).
3. Same T0 path → CLOSED.

For a T2 (REQUIRE_APPROVAL) demo, fabricate a non-reversible proposal —
see the orchestrator's `_synthetic_proposal` and set
`reversible=false, financial_impact=50000` to demonstrate the gate.

## Beat 3 — Structural block on DELETE_DATA (45 s)

Open the HTML dashboard. In the "Inject Proposal" form:

- action_type = `db.drop`
- tier = `T3_DESTRUCTIVE`
- version = `1`
- Submit

Live trace shows: `BLOCKED — T3_DESTRUCTIVE structurally blocked`.

Highlight the live ledger row. Open `services/action-broker-go/cmd/server/static_check_test.go`
and run:

```bash
go test ./cmd/server -run TestNoExecutorForT3 -v
```

That test walks the AST and **fails the build** if any forbidden
function name (`executedestructive`, `rundestructive`,
`applydestructive`, `dispatchdestructive`, `deleteproduction`,
`alterproductionschema`) ever appears in the broker.

## Beat 4 — Tamper-evident ledger (30 s)

Submit 3 proposals in quick succession. The HTML dashboard's ledger panel
fills up.

```bash
curl -s http://localhost:8080/api/ledger/verify | jq
```

```json
{ "ok": true, "head_seq": 2 }
```

Then run the Python test that detects tampering:

```bash
make test-py -k verify_chain_detects_tamper
```

Highlight the SHA-256 chain — each entry's `previous_hash` points to the
prior `entry_hash`.

## Beat 5 — The full FSM in one image (15 s)

Show the README Mermaid diagram. Point at the seven GEAP capabilities
mapped to Chronos components: Registry, Runtime, Memory, Identity,
Gateway, Model Armor, Observability.

## Closing (15 s)

> "Chronos never trusts the model with execution. Every proposal is
> typed, debated, allow-listed, signed, and logged. T3 destructive
> actions are blocked by code, not by prompt — proven by a static
> check that fails the build the moment anyone tries to add an
> executor path."