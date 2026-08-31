CHRONOS: AI Coding Implementation Guide
Fortified Enterprise Fleet Track — Grand Prize Contender
🎯 What You Are Building
A governed incident-remediation control plane that turns a pipeline failure into a verified, policy-checked repair proposal, while making unauthorized production mutation impossible for the demo system.

The winning insight: "Chronos does not trust the model with execution. Every proposal passes typed validation, identity checks, deterministic policy, approval gates, verification, and audit."

📋 Quick Reference: What to Build
#	Component	Language	Mandatory	Time
1	Orchestrator	Python (ADK)	✅	1 hour
2	Detection Agent	Python (ADK)	✅	30 min
3	Debate Proposer	Python (ADK)	✅	30 min
4	Debate Auditor	Python (ADK)	✅	30 min
5	Action Broker	Go (A2A)	✅	2 hours
6	Immutable Ledger	Python (Firestore)	✅	30 min
7	Dashboard	Streamlit/React	✅	1 hour
Total: ~6-7 hours with AI coding assistance

📁 Repository Structure for AI Coding
text
chronos/
├── apps/
│   ├── orchestrator/
│   │   ├── agent.py          # Root orchestrator
│   │   ├── detection.py      # Detection Agent
│   │   ├── debate.py         # Proposer + Auditor
│   │   ├── workflow.py       # State machine
│   │   ├── schemas.py        # Pydantic models
│   │   ├── session.py        # FirestoreSessionService
│   │   ├── memory.py         # Memory Bank
│   │   ├── api.py            # FastAPI entry
│   │   └── requirements.txt
│   └── dashboard/
│       └── streamlit_app.py
├── services/
│   └── action-broker-go/
│       ├── cmd/server/main.go
│       ├── internal/policy/policy.go
│       ├── internal/a2a/server.go
│       ├── internal/registry/registry.go
│       └── go.mod
├── contracts/
│   ├── incident.schema.json
│   ├── failure-classification.schema.json
│   ├── action-proposal.schema.json
│   └── policy-decision.schema.json
├── infra/
│   ├── firestore.rules
│   ├── pubsub.md
│   └── iam.md
├── fixtures/
│   ├── incidents/schema-drift.json
│   └── incidents/api-timeout.json
├── docs/
│   ├── architecture.md
│   ├── threat-model.md
│   └── demo-script.md
├── Dockerfile
├── docker-compose.yml
├── Makefile
└── README.md
🔑 The Core Insight: T3 Structurally Unreachable
This is your #1 differentiator. T3 actions are blocked by code, not by prompt.

In the Go Action Broker:
go
// action-broker-go/internal/policy/policy.go
package policy

type ActionTier string

const (
    T0 ActionTier = "T0" // Reversible, sandbox only
    T1 ActionTier = "T1" // Reversible, requires approval
    T2 ActionTier = "T2" // Irreversible, requires approval + ticket
    T3 ActionTier = "T3" // STRUCTURALLY UNREACHABLE — BLOCKED BY CODE
)

type Proposal struct {
    ID              string `json:"id"`
    ProposedBy      string `json:"proposed_by"`
    Action          string `json:"action"`
    Target          string `json:"target"`
    Reversible      bool   `json:"reversible"`
    FinancialImpact int    `json:"financial_impact"`
    Rollback        string `json:"rollback"`
}

type Decision struct {
    Status string      `json:"status"` // ALLOW, APPROVAL_REQUIRED, BLOCKED
    Tier   ActionTier  `json:"tier"`
    Reason string      `json:"reason,omitempty"`
}

func (b *Broker) Decide(proposal Proposal, caller Identity) Decision {
    // 1. Check registry
    if !b.registry.IsApproved(caller.AgentID, caller.Version) {
        return Block("UNREGISTERED_AGENT")
    }

    // 2. Check policy allow-list
    if !b.policy.AllowedAction(proposal.Action) {
        return Block("ACTION_NOT_ALLOWED")
    }
    if !b.policy.AllowedTarget(proposal.Target) {
        return Block("TARGET_NOT_ALLOWED")
    }

    // 3. T3: Structurally unreachable — BLOCKED BY CODE
    if proposal.Action == "DELETE_DATA" || proposal.Action == "ALTER_PRODUCTION_SCHEMA" {
        return Block("T3_PRODUCTION_MUTATION_BLOCKED")
    }

    // 4. T2: High risk, requires approval
    if proposal.FinancialImpact > 10000 {
        return RequireApproval("T2_HIGH_FINANCIAL_IMPACT")
    }

    // 5. T1: Reversible but material
    if !proposal.Reversible {
        return RequireApproval("T1_NON_REVERSIBLE")
    }

    // 6. T0: Safe, sandbox only
    return AllowSandbox("T0_SANDBOX_ONLY")
}
The critical property: A Decision{Status: "BLOCKED"} has no executor capability. The broker's API never accepts arbitrary execution requests. This is proven by tests.

🚀 AI Coding Prompts (Copy & Paste in Order)
Prompt 1: Establish Constraints
text
You are implementing Chronos, a governed incident-remediation control plane for the Google All Things Agentic Hackathon, Fortified Enterprise Fleet track.

Read the repository and do not invent APIs. First produce a plan, identify the pinned versions of:
- Python ADK (google-adk)
- Google Cloud libraries (google-cloud-firestore, google-cloud-aiplatform, google-cloud-modelarmor, google-cloud-pubsub)
- Go (1.21+)
- A2A SDK

List every external dependency. Do not write production execution tools yet.

The system must separate LLM proposals from deterministic policy enforcement.
Every generated change must include tests and must preserve the contracts in /contracts.

Stop and ask for clarification if an API is not available in the pinned version.
Prompt 2: Create Data Contracts
text
Create JSON schemas in /contracts for:
1. Incident (incident_id, pipeline_id, error_log, context)
2. FailureClassification (failure_type, severity, impact, root_cause)
3. ActionProposal (proposal_id, incident_id, proposed_by, action, target, reversible, financial_impact, rollback, success_criteria)
4. PolicyDecision (status, tier, reason, timestamp)

FailureType enum: SCHEMA_CHANGE, API_TIMEOUT, DATA_CORRUPTION, NETWORK, AUTH, UNKNOWN
Action enum: ROLLBACK_SCHEMA, REPLAY_BATCH, ROTATE_TOKEN, DELETE_DATA, ALTER_PRODUCTION_SCHEMA

The Go broker must reject unknown actions, missing fields, negative financial impact, malformed identifiers, and targets outside an allow-list.
Never allow the model to supply an executable URL, shell command, SQL statement, or IAM principal directly.
Prompt 3: Scaffold the Orchestrator
text
Build the Python ADK orchestrator in apps/orchestrator/agent.py using the pinned SDK.

Create a Runner with:
- FirestoreSessionService configured for durable state
- VertexAiMemoryBankService configured for cross-session memory

Add agents:
1. DetectionAgent: LlmAgent with Gemini 3.5 Flash, strict Pydantic output schema (FailureClassification)
2. DebateProposer: LlmAgent with Gemini 3.5 Flash, proposes repair strategies
3. DebateAuditor: LlmAgent with Gemini 3.5 Flash, attacks proposals with counterarguments

Implement a controller that performs at most three proposer/auditor rounds.
Store the full debate transcript.

The model must never receive a direct production-write tool.

Add unit tests for: schema rejection, timeout, retry, and the three-round limit.
Prompt 4: Implement the Workflow State Machine
text
Implement the Chronos state machine in apps/orchestrator/workflow.py.

States: RECEIVED → CLASSIFIED → DEBATING → PROPOSED → POLICY_REVIEW → APPROVAL_REQUIRED/BLOCKED/EXECUTING → VERIFIED → CLOSED

Persist incident_id, run_id, state, attempt_count, and timestamps after each transition.
Make processing idempotent by incident_id.

Add Pub/Sub handler logic with a dead-letter topic and a deterministic replay command.
No state transition may execute an action without a policy decision.
Prompt 5: Implement the Go Action Broker (A2A)
text
Implement a separately deployable Go Action Broker in services/action-broker-go/.

Use the actual A2A server pattern including:
- Agent card endpoint (/agent-card)
- Health endpoint (/health)
- A2A handler (/a2a)

Implement:
- Registry check: validate caller agent ID and version
- Policy evaluation: deterministic allow-list
- Decision: ALLOW_SANDBOX, REQUIRE_APPROVAL, or BLOCKED

CRITICAL: DELETE_DATA and ALTER_PRODUCTION_SCHEMA must return BLOCKED and must have NO code path to an executor.

Add tests:
- Table-driven tests for all policy decisions
- Fuzz tests for malformed JSON
- Replay/idempotency tests
- Negative test proving blocked decisions cannot invoke the executor

Use actual A2A Protocol support (RemoteA2aAgent in Python), not just a /a2a endpoint.
Prompt 6: Implement the Immutable Ledger
text
Implement a Firestore-backed tamper-evident ledger in apps/orchestrator/ledger.py.

Use a Firestore transaction or single-writer mechanism for concurrency safety.
Assign a sequence number atomically.
Use canonical sorted-key JSON.
Include previous_hash in each entry.
Provide verify_chain() that checks sequence continuity and hash integrity.
Do NOT hash an unresolved server timestamp.

Add Firestore security rules in infra/firestore.rules that deny update and delete for normal principals.

Add tests:
- Concurrent-writer tests
- Altered-record detection tests
- Missing-record detection tests
- Duplicate-event tests

Document the trust model: "tamper-evident under the stated trust model," not "absolutely immutable."
Prompt 7: Implement the Detection Agent
text
Create DetectionAgent in apps/orchestrator/detection.py.

Use LlmAgent with:
- model="gemini-3.5-flash"
- Pydantic output schema: FailureClassification
- instruction: "Analyze the provided pipeline error log. Classify the failure with failure_type (SCHEMA_CHANGE, API_TIMEOUT, DATA_CORRUPTION, NETWORK, AUTH, UNKNOWN), severity (CRITICAL, HIGH, MEDIUM, LOW), impact (which downstream systems are affected), and root_cause (1-2 sentence summary). Output valid JSON."

If validation fails, route to "needs human review" state — NOT automatic repair.
Prompt 8: Implement Debate Agents
text
Create DebateProposer and DebateAuditor in apps/orchestrator/debate.py.

DebateProposer:
"You are the Proposer. Given a failure classification, propose a repair strategy with step-by-step actions, estimated time, rollback strategy, and success criteria. Be prepared to defend against Auditor counterarguments. Focus on speed, correctness, minimal disruption."

DebateAuditor:
"You are the Auditor. Attack the Proposer's plan. Find flaws in edge cases, hidden dependencies, resource constraints, security concerns, and rollback feasibility. Provide 3-5 concrete counterarguments. The goal is to HARDEN the plan."

The controller, not the model, owns the three-round limit.
The auditor must receive the original incident and proposed plan, not merely a prose summary.
Prompt 9: Deploy to Cloud Run
text
Generate deployment files:

Dockerfile for Python orchestrator:
FROM python:3.11-slim
WORKDIR /app
COPY apps/orchestrator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV GOOGLE_CLOUD_PROJECT=${PROJECT_ID}
ENV VERTEX_AI_LOCATION=us-central1
CMD ["python", "-m", "uvicorn", "apps.orchestrator.api:app", "--host", "0.0.0.0", "--port", "8080"]

Dockerfile for Go Action Broker:
FROM golang:1.21-alpine
WORKDIR /app
COPY services/action-broker-go/go.mod .
COPY services/action-broker-go/ .
RUN go build -o action-broker cmd/server/main.go
CMD ["./action-broker"]

Deploy commands with scale-to-zero:
gcloud run deploy chronos-orchestrator --source . --platform managed --region us-central1 --min-instances 0 --max-instances 10 --memory 2Gi --cpu 2
gcloud run deploy chronos-action-broker --source ./services/action-broker-go --platform managed --region us-central1 --min-instances 0 --max-instances 5 --memory 512Mi

Enable APIs:
gcloud services enable aiplatform.googleapis.com run.googleapis.com firestore.googleapis.com pubsub.googleapis.com modelarmor.googleapis.com cloudtrace.googleapis.com
Prompt 10: Create Dashboard
text
Create a Streamlit dashboard in apps/dashboard/streamlit_app.py.

Views:
1. Incident List: Show all incidents with status
2. Incident Detail: Show classification, debate transcript, policy decision, ledger entry
3. Ledger Viewer: Show hash chain, verify chain button
4. System Status: Show Cloud Run, Firestore, Pub/Sub health

Connect to Firestore to read incident and ledger data.
No write capability in the dashboard.
Prompt 11: Security Hardening
text
Perform a threat-model review of Chronos. Identify and mitigate:
- Prompt injection
- Tool poisoning
- Confused deputy
- Replay attacks
- Privilege escalation
- Data leakage
- SSRF
- Credential exposure
- Denial of service
- Audit tampering

Add controls:
- Input/output screening (Model Armor)
- Redaction of sensitive data
- Strict schemas
- Allow-listed targets only
- Service-account separation
- Request deadlines
- Correlation IDs
- Rate limits
- Fail-closed behavior

Generate docs/threat-model.md mapping each risk to a test and implementation control.
Prompt 12: Generate Submission Materials
text
Generate:
1. README.md with:
   - One-sentence description
   - Architecture diagram (Mermaid)
   - Setup and deployment instructions
   - Contract and policy descriptions
   - Test report summary

2. docs/architecture.md with:
   - Full system architecture diagram
   - Component descriptions
   - Data flow
   - GEAP capability mapping

3. Text description (300 words) for the hackathon submission:
   - Problem: Data pipeline failures take hours to fix
   - Solution: Chronos reduces incidents to reviewed, policy-safe decisions
   - Features: Detection, Debate, Action Broker, Ledger
   - Technologies: Gemini 3.5 Flash, ADK, Go, A2A, Cloud Run, Firestore