# Chronos — Deploy to Google Cloud

This guide deploys Chronos to Cloud Run with Firestore + Pub/Sub using
the **gcloud CLI**. Cost-control flags (`--min-instances=0`,
`--max-instances=1`, scale-to-zero idle) keep the bill near zero when
nothing is happening.

Estimated cost while idle: **$0/month** (scale to zero).
Under demo load (1 req/sec for 4 minutes): **<$0.10**.

## 0. Prerequisites

Chronos uses the **Gemini Interactions API** on Gemini Enterprise Agent
Platform (GEAP). Per the GEAP skill spec, base-model calls are not
supported on the platform — you must target provisioned agents. Before
deploying the orchestrator, provision three agents in the GEAP console:

| Provisioned agent id         | Output schema            |
|------------------------------|--------------------------|
| `chronos.detection_agent`    | `FailureClassification`  |
| `chronos.debate_proposer`    | `ActionProposal`         |
| `chronos.debate_auditor`     | `AuditCritique`          |

The agent system instructions live in
`apps/orchestrator/agents/{detection,proposer,auditor}.py` as
`SYSTEM_PROMPT` constants — paste them into the GEAP console when you
provision each agent. Copy-paste-ready form values (Name, Description,
Instructions blocks) are in **[AGENT_PROMPTS.md](AGENT_PROMPTS.md)** at
the repo root.

**Single-project setup.** Everything in Chronos lives in
`annular-surf-439113-v6` for this deployment — the three GEAP agents,
Cloud Run, Firestore, and Pub/Sub all share the same project. Agent
IDs (`chronos.detection_agent`, `chronos.debate_proposer`,
`chronos.debate_auditor`) are global and work without any
cross-project IAM grants.

```bash
# Authenticate with Application Default Credentials
gcloud auth login
gcloud auth application-default login

# Pick a project ID you own (infrastructure project — different from
# the project that hosts the GEAP agents, see step 4b below).
export PROJECT_ID=annular-surf-439113-v6
gcloud config set project $PROJECT_ID

# Enable required APIs
gcloud services enable \
  aiplatform.googleapis.com \
  run.googleapis.com \
  firestore.googleapis.com \
  pubsub.googleapis.com \
  modelarmor.googleapis.com \
  cloudtrace.googleapis.com \
  secretmanager.googleapis.com

# Pick a region
export REGION=us-central1
```

```bash
# Google Cloud SDK
gcloud --version   # >= 450.0.0 recommended

# Authenticate
gcloud auth login
gcloud auth application-default login

# Pick a project ID you own (infrastructure project — different from
# the project that hosts the GEAP agents, see step 4b below).
export PROJECT_ID=annular-surf-439113-v6
gcloud config set project $PROJECT_ID

# Enable required APIs
gcloud services enable \
  aiplatform.googleapis.com \
  run.googleapis.com \
  firestore.googleapis.com \
  pubsub.googleapis.com \
  modelarmor.googleapis.com \
  cloudtrace.googleapis.com \
  secretmanager.googleapis.com

# Pick a region
export REGION=us-central1
```

## 1. Service accounts

```bash
for SA in chronos-orchestrator chronos-action-broker chronos-dashboard; do
  gcloud iam service-accounts create $SA --project=$PROJECT_ID
done

# Orchestrator: Vertex AI user, Firestore user, Pub/Sub publisher+subscriber
for ROLE in roles/aiplatform.user roles/datastore.user roles/pubsub.publisher roles/pubsub.subscriber roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:chronos-orchestrator@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="$ROLE"
done

# Broker: NO Firestore write role — only logging
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:chronos-action-broker@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/logging.logWriter"

# Dashboard: read-only Datastore
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:chronos-dashboard@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/datastore.viewer"
```

## 2. Firestore + Pub/Sub

```bash
# Firestore in Native mode (required for sessions + ledger + workflow)
gcloud firestore databases create --location=$REGION --project=$PROJECT_ID

# Deploy security rules
gcloud firestore deploy infra/firestore.rules --project=$PROJECT_ID

# Pub/Sub topics + DLQ
gcloud pubsub topics create chronos-incidents --project=$PROJECT_ID
gcloud pubsub topics create chronos-incidents-dlq --project=$PROJECT_ID
gcloud pubsub subscriptions create chronos-incidents-sub \
  --topic=chronos-incidents \
  --ack-deadline=60 \
  --message-retention-duration=7d \
  --project=$PROJECT_ID

# Push the subscription to the orchestrator URL (set after deploy)
# gcloud pubsub subscriptions update chronos-incidents-sub \
#   --push-endpoint=$ORCHESTRATOR_URL/push \
#   --project=$PROJECT_ID
```

## 3. Deploy the Action Broker

```bash
cd services/action-broker-go

gcloud run deploy chronos-action-broker \
  --source . \
  --region=$REGION \
  --project=$PROJECT_ID \
  --service-account chronos-action-broker@$PROJECT_ID.iam.gserviceaccount.com \
  --min-instances 0 \
  --max-instances 1 \
  --memory 512Mi \
  --cpu 1 \
  --no-allow-unauthenticated \
  --set-env-vars CHRONOS_BROKER_ADDR=:8080

# Grant the orchestrator permission to call the broker
BROKER_URL=$(gcloud run services describe chronos-action-broker \
  --region=$REGION --project=$PROJECT_ID --format='value(status.url)')
gcloud run services add-iam-policy-binding chronos-action-broker \
  --region=$REGION --project=$PROJECT_ID \
  --member="serviceAccount:chronos-orchestrator@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

## 4. Deploy the Orchestrator

```bash
cd ../..

gcloud run deploy chronos-orchestrator \
  --source . \
  --region=$REGION \
  --project=$PROJECT_ID \
  --service-account chronos-orchestrator@$PROJECT_ID.iam.gserviceaccount.com \
  --min-instances 0 \
  --max-instances 1 \
  --memory 2Gi \
  --cpu 2 \
  --allow-unauthenticated \
  --set-env-vars \
    GOOGLE_CLOUD_PROJECT=$PROJECT_ID,\
    GOOGLE_GENAI_USE_VERTEXAI=true,\
    VERTEX_AI_LOCATION=global,\
    CHRONOS_BROKER_URL=$BROKER_URL,\
    CHRONOS_API_PORT=8080

ORCHESTRATOR_URL=$(gcloud run services describe chronos-orchestrator \
  --region=$REGION --project=$PROJECT_ID --format='value(status.url)')

# Now wire the Pub/Sub push subscription to the orchestrator
gcloud pubsub subscriptions update chronos-incidents-sub \
  --push-endpoint=$ORCHESTRATOR_URL/push \
  --project=$PROJECT_ID
```

## 5. Deploy the Dashboard (Streamlit)

```bash
cd apps/dashboard

gcloud run deploy chronos-dashboard \
  --source . \
  --region=$REGION \
  --project=$PROJECT_ID \
  --service-account chronos-dashboard@$PROJECT_ID.iam.gserviceaccount.com \
  --min-instances 0 \
  --max-instances 1 \
  --memory 1Gi \
  --allow-unauthenticated \
  --set-env-vars CHRONOS_API_URL=$ORCHESTRATOR_URL
```

## 6. Verify deployment

```bash
# Health check
curl $ORCHESTRATOR_URL/healthz
# {"status":"ok", ...}

# Ledger verify (chain is empty initially)
curl $ORCHESTRATOR_URL/api/ledger/verify
# {"ok": true, "head_seq": null}

# Submit a test incident
curl -X POST $ORCHESTRATOR_URL/api/incidents \
  -H "Content-Type: application/json" \
  -d @../../fixtures/incidents/schema-drift.json
```

## 7. Tear down (cost $0)

```bash
gcloud run services delete chronos-orchestrator chronos-action-broker chronos-dashboard \
  --region=$REGION --project=$PROJECT_ID --quiet

gcloud pubsub subscriptions delete chronos-incidents-sub --project=$PROJECT_ID --quiet
gcloud pubsub topics delete chronos-incidents chronos-incidents-dlq --project=$PROJECT_ID --quiet

# Optional — wipe Firestore
gcloud firestore databases delete --project=$PROJECT_ID --quiet
```

## Cost-control reference

| Flag                          | Effect                                                   |
|-------------------------------|----------------------------------------------------------|
| `--min-instances 0`           | Scale to zero when idle                                  |
| `--max-instances 1`           | Cap concurrency (saves money, fine for demos)            |
| `--cpu 1` (broker)            | 1 vCPU is enough for A2A + ledger append                 |
| `--memory 512Mi` (broker)     | Broker holds only recent spans in memory                 |
| `--no-allow-unauthenticated`  | Broker requires service-account auth                     |
| `--timeout 60`                | Cap request duration (prevents runaway billing)          |

## What "deployment proof" looks like

After step 6, run:

```bash
gcloud run services list --region=$REGION --project=$PROJECT_ID
```

Expected output (your URLs will differ):

```
SERVICE                REGION       URL                                           LATEST_REVISION
chronos-orchestrator   us-central1  https://chronos-orchestrator-xyz.a.run.app   chronos-orchestrator-00001-abc
chronos-action-broker  us-central1  https://chronos-action-broker-xyz.a.run.app  chronos-action-broker-00001-def
chronos-dashboard      us-central1  https://chronos-dashboard-xyz.a.run.app      chronos-dashboard-00001-ghi
```

Open `$ORCHESTRATOR_URL/api/ledger/verify` and you should see `{"ok": true}`.
Open `$ORCHESTRATOR_URL/` for the HTML dashboard.
Open the dashboard URL for the Streamlit view.

That output is your **proof of deployment** — record the screen in the
demo video.