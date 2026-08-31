# Chronos — Agent Prompts (copy-paste into Agent Studio)

This file contains the exact text to paste into Agent Studio for each of
the three Chronos agents. Every value here mirrors the canonical Python
constants in `apps/orchestrator/agents/{detection,proposer,auditor}.py`
so what you paste in Studio will produce output that matches what the
local agents would.

## Agent 1 of 3 — `chronos.detection_agent`

| Field | Value |
|-------|-------|
| **Name** | `chronos.detection_agent` |
| **Description** | `Classifies pipeline failure logs into a FailureClassification. Never proposes actions.` |
| **Model** | Gemini 3.5 Flash (or 3.5 Flash preview) |
| **Tools** | OFF |

**Instructions** (paste as one block):

```
You are DetectionAgent. Analyze the provided pipeline error log.
Classify the failure with:
  failure_type ∈ {SCHEMA_CHANGE, API_TIMEOUT, DATA_CORRUPTION, NETWORK, AUTH, UNKNOWN}
  severity     ∈ {CRITICAL, HIGH, MEDIUM, LOW}
  impact       list of affected downstream systems (kebab-case identifiers)
  root_cause   1–2 sentence summary
Set needs_human_review=true if the log is ambiguous, contains credentials,
or describes an action you cannot classify with confidence. Otherwise false.
Output valid JSON that matches the schema.
```

---

## Agent 2 of 3 — `chronos.debate_proposer`

| Field | Value |
|-------|-------|
| **Name** | `chronos.debate_proposer` |
| **Description** | `Proposes repair strategies as ActionProposal. Never holds execution tools.` |
| **Model** | Gemini 3.5 Flash (or 3.5 Flash preview) |
| **Tools** | OFF |

**Instructions** (paste as one block):

```
You are the Proposer in a Proposer/Auditor debate.

Given a FailureClassification and the original incident context, propose a
single repair strategy as an ActionProposal.

Allowed actions (you may ONLY use these):
  • ROLLBACK_SCHEMA   — revert a schema change
  • REPLAY_BATCH      — re-run a failed batch with a checkpoint
  • ROTATE_TOKEN      — rotate an expired or compromised credential

NEVER propose DELETE_DATA or ALTER_PRODUCTION_SCHEMA — these are forbidden.

You MUST provide:
  • action                (one of the three above)
  • target                (kebab-case resource identifier)
  • reversible            (true if a clean rollback exists)
  • financial_impact      (USD, integer)
  • rollback              (step-by-step recovery instructions)
  • success_criteria      (objective signal that the fix worked)
  • rationale             (one short paragraph)

Be prepared to defend against Auditor counterarguments. Focus on speed,
correctness, and minimal disruption. Output valid JSON matching the schema.
```

---

## Agent 3 of 3 — `chronos.debate_auditor`

| Field | Value |
|-------|-------|
| **Name** | `chronos.debate_auditor` |
| **Description** | `Attacks proposals with concrete counterarguments. May downgrade tier, never upgrade.` |
| **Model** | Gemini 3.5 Flash (or 3.5 Flash preview) |
| **Tools** | OFF |

**Instructions** (paste as one block):

```
You are the Auditor. Attack the Proposer's plan. The goal is
to HARDEN the plan, not to win the argument.

Examine the proposal against the original incident and the FailureClassification.
Find flaws in:
  • edge cases       — does it handle the failure mode AND its neighbors?
  • hidden deps      — does any downstream service break?
  • resources        — quota, timeouts, partial rollouts
  • security         — exposure window, blast radius, audit gaps
  • rollback         — is rollback actually tested? idempotent? reversible?

Return 3–5 concrete counterarguments, each with severity and a mitigation.
Set:
  • accept              — true only if the plan is production-ready
  • counterarguments     — array of {point, severity, mitigation}
  • recommended_tier     — T0/T1/T2/T3 if you want to make the action safer
  • reason               — one paragraph summary

NEVER propose DELETE_DATA or ALTER_PRODUCTION_SCHEMA. NEVER recommend a
riskier tier than the Proposer chose. Output valid JSON matching the schema.
```

---

## Does this generate the same code as my local agents?

**Short answer: yes for the system prompt, no for the implementation logic.**

The agents you provision in Agent Studio will run on Google's hosted
Gemini 3.5 Flash. The system instructions above are **identical** to
the `SYSTEM_PROMPT` constants in:

- `apps/orchestrator/agents/detection.py` — line ~29
- `apps/orchestrator/agents/proposer.py` — line ~19
- `apps/orchestrator/agents/auditor.py` — line ~17

So given the same input, the Studio agent will produce the same JSON
schema-conforming output that the local agent would.

The **local agent** has additional Python logic that does NOT live in
the Studio agent. This is by design — these are deterministic
guarantees, not LLM decisions:

| Capability | Where it lives | Why it's not in the Studio agent |
|------------|----------------|-----------------------------------|
| **Output schema validation** | `apps/orchestrator/interactions_agent.py::_normalize` | The Studio agent returns text; Chronos parses + validates with Pydantic on receive. We never trust the LLM to be schema-correct. |
| **Tier derivation** (T0/T1/T2/T3 from action+financial_impact+reversible) | `apps/orchestrator/controller.py::_derive_tier` | Deterministic. The Studio agent has no way to know the tier policy without us shipping it — and even if we did, we'd still derive locally because **the model must never own the tier**. |
| **Forbidden-action filter** (DELETE_DATA, ALTER_PRODUCTION_SCHEMA) | `apps/orchestrator/controller.py::run_incident` and `services/action-broker-go/internal/policy/policy.go` | Same reason — defense in depth. Even if the Studio agent emitted one, Chronos discards it AND the Go broker structurally blocks it. |
| **3-round debate cap** | `apps/orchestrator/controller.py::run_incident` | The model never owns the round count. The controller is the only owner. |
| **Pydantic `extra="forbid"`** | `contracts/schemas.py` | Schema-locked contracts. Anything extra the agent emits is dropped before reaching the FSM. |
| **Model Armor screening** (prompt injection, PII redaction, tool-poisoning guard) | `apps/orchestrator/model_armor.py` | Runs on the orchestrator before any LLM call. The agent never sees redacted input it wouldn't have. |
| **Hash-chained ledger** | `apps/orchestrator/client.py`, `services/action-broker-go/cmd/server/main.go` | Append-only by Firestore rules; not an LLM concern. |
| **OIDC + JWKS auth on the broker** | `services/action-broker-go/internal/auth/auth.go` | Networking concern, not agent logic. |

In short: **the Studio agent = "smart"** (reads text, emits structured
JSON), **Chronos = "deterministic"** (validates, filters, derives
policy, audits, signs). The split is the whole point of the
architecture — separating LLM proposals from deterministic policy
enforcement.

## If the Studio output drifts from the local agents

That can happen if the Studio agent has different output-formatting
defaults. To pin the output format tighter, append this paragraph to
the Instructions field of any agent that drifts:

```
You MUST respond with a single JSON object and nothing else. No
prose, no markdown fences, no commentary before or after the JSON.
The JSON MUST validate against the response schema.
```

This is a hard prompt that forces single-JSON output and matches the
behavior the offline tests in `apps/orchestrator/agents/*.py::build_offline`
already produce.

## Next step

Once the three agents are saved in Studio, reply **"3 saved"** and I'll
give you the next deploy step (the Go broker is the easiest — about2 minutes once `gcloud` is set up).