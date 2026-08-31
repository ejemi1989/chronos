# Chronos — Operate locally

## 1. Start the Action Broker (Go)

```bash
cd action_broker
CHRONOS_BROKER_ADDR=:8080 go run ./cmd/broker
```

You should see:

```
chronos action broker listening :8080
```

## 2. Open the dashboard

Visit `http://localhost:8080/` in your browser. The dashboard:

- injects an `ActionProposal` (T1, T2, or T3)
- POSTs to `/a2a/v1/invoke` over the A2A protocol
- renders the broker's `Decision`
- appends to the tamper-evident ledger shown at the bottom

## 3. Run the test suite

Python (orchestrator + contracts + ledger):

```bash
.venv/bin/python -m pytest tests/ orchestrator/tests/ -v
```

Go (broker + policy + structural unreachable proofs):

```bash
cd action_broker
go test ./...
```

The Go structural tests walk the source tree and **fail the build** if:

- any function name contains `executedestructive`, `rundestructive`,
  `applydestructive`, `dispatchdestructive`, `deleteproduction`, or
  `alterproductionschema`
- any case in a `switch` whose label is `TierDestructive` returns
  anything other than `DecisionBlocked`

This is your **proof** that T3 destructive actions are structurally
unreachable, not merely policy-enforced.

## 4. Endpoints

| Method | Path                     | Purpose                          |
|--------|--------------------------|----------------------------------|
| GET    | `/`                      | Dashboard HTML                   |
| GET    | `/healthz`               | Liveness probe                   |
| GET    | `/.well-known/agent.json`| A2A agent card                   |
| POST   | `/a2a/v1/invoke`         | Submit an ActionProposal         |
| GET    | `/ledger/recent`         | Latest 12 ledger entries         |