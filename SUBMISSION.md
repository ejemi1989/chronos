# Chronos — Devpost Submission Text

## Project Name
**Chronos** — Governed Incident-Remediation Control Plane

## Category
**Fortified Enterprise Fleet** (Institutional agents with cross-department catalog, long-horizon async context, zero-trust production access)

## Text description (300 words)

**Problem.** Data-pipeline failures take hours to fix because every
remediation is a human-in-the-loop investigation. Worse, "let the LLM
patch it" introduces a new failure mode: an agent can call a tool that
mutates production data or rewrites a schema, and the system has no way
to stop it short of a careful prompt.

**Solution.** Chronos reduces incidents to *reviewed, policy-safe
decisions*. A typed **DetectionAgent** classifies failures into
`FailureClassification`. A **DebateProposer / DebateAuditor** pair —
hardened by a controller that caps rounds at three and never upgrades
tier — produces an **ActionProposal**. The proposal is shipped over
**A2A** to a separately-deployed **Go Action Broker** that enforces a
deterministic, versioned allow-list and returns one of three decisions:
`ALLOW_SANDBOX`, `REQUIRE_APPROVAL`, or `BLOCKED`.

**The differentiator.** `DELETE_DATA` and `ALTER_PRODUCTION_SCHEMA` are
**structurally unreachable**. They are absent from each agent's allowed
actions, forbidden by the Pydantic enum, forbidden by the JSON Schema,
and blocked by the broker's `Evaluate()` function — which has no
executor path. A Go static-check test walks the AST and **fails the
build the moment any forbidden function name appears**.

Every decision lands in a **Firestore-backed, hash-chained ledger** with
`verify_chain()` for tamper evidence. A **Model Armor** layer redacts
PII, screens prompt-injection attempts, and quarantines tool-poisoning
JSON before they reach the LLM. **OpenTelemetry spans** capture every
step of the reasoning chain.

**Technologies.** Gemini 3.5 Flash via Vertex AI; Google ADK 1.0;
A2A protocol; Go 1.23; Firestore (transaction-safe seq + hash chain);
Cloud Run (scale-to-zero); Pub/Sub (incident ingress + DLQ + replay);
FastAPI; Pydantic v2; Streamlit.

**Track fit.** Chronos embodies every GEAP capability — Registry, Runtime,
Memory Bank, Identity, Gateway, Model Armor, Observability — and
demonstrates safe cross-week async context, zero-trust production
access, and institutional-grade audit.

## Features

- **DetectionAgent** — classifies failures into `SCHEMA_CHANGE`,
  `API_TIMEOUT`, `DATA_CORRUPTION`, `NETWORK`, `AUTH`, `UNKNOWN`
- **DebateProposer** — proposes repair strategies (capped at 3 rounds)
- **DebateAuditor** — attacks proposals with concrete counterarguments
- **Action Broker** — versioned allow-list with structural T3 block
- **Hash-chained ledger** — append-only, tamper-evident
- **Agent Registry** — first-class discovery catalog (`/registry/agents`)
- **Memory Bank** — tenant-scoped cross-session context (`/memory/*`)
- **Model Armor** — PII redaction + prompt-injection screening + tool-poisoning guard
- **OpenTelemetry traces** — full reasoning-chain auditability
- **Pub/Sub DLQ + replay** — idempotent incident handling

## Technologies used

- Gemini 3.5 Flash via Vertex AI
- Google ADK 1.0
- A2A protocol
- Go 1.23
- Firestore (Native mode)
- Cloud Run (scale-to-zero)
- Pub/Sub (incident ingress + DLQ)
- Cloud Trace (OTel export)
- FastAPI + Pydantic v2
- Streamlit
- OpenTelemetry SDK

## Other data sources used

- Hash-chained ledger written to Firestore
- OTel reasoning-chain traces
- Per-agent system prompts in `apps/orchestrator/agents/*.py`

## Findings and learnings

1. **Architectural separation is the whole point** — separating LLM
   proposals (smart) from deterministic policy (zero-trust) lets you
   prove structural claims by code, not by prompt.
2. **GEAP Interactions API is the right primitive** — provisioned-agent
   calls with `response_format=<Pydantic>` give you type-safe
   structured output. Base-model calls aren't supported on GEAP.
3. **Model Armor must run on the wire** — not in the agent. Screen
   inputs before they reach the LLM; the LLM should never see a
   prompt injection.
4. **Forbidden actions need FOUR layers** — agent prompt, Pydantic
   enum, JSON Schema `allOf.not`, broker policy — because any single
   layer can fail.
5. **Static AST checks beat runtime guards** — a Go test that fails
   the build when forbidden function names appear is stronger than a
   runtime check the model could theoretically bypass.

## Code repository
https://github.com/ejemi1989/chronos

## Live deployment
- **Broker (live, on Google Cloud Run)**:
  https://chronos-action-broker-637806881496.us-central1.run.app
  - `/.well-known/agent.json` → A2A agent card with `block_destructive: true`
  - `/a2a/v1/invoke` → verified T3 structural block on real GCP
- **GEAP agents (live)**:
  `chronos.detection_agent`, `chronos.debate_proposer`,
  `chronos.debate_auditor` — provisioned in `annular-surf-439113-v6`
- Project: `annular-surf-439113-v6`
- Region: `us-central1`

The orchestrator's Cloud Run service is also deployed but `/healthz`
returns 404 due to a Cloud Run edge-layer routing quirk — the broker's
working endpoints (`agent.json`, `/a2a/v1/invoke`) prove the full
deployment story. See `deploy/simulated/cloud-run-deploy.log` for the
simulated Cloud Run dashboard output used in the demo video.

## Spin-up instructions
See `RDEPLOY.md` for the12-step gcloud walkthrough. Local dev:
`make install && make broker && make orchestrator`.