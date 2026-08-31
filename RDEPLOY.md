# Chronos — Deploy runbook for $USER

> **TL;DR.** I can't authenticate as you, so this runbook is the hand-off.
> Follow steps 1–9 below in order. The whole thing takes ~20 minutes
> and costs ~$0.00 at idle. Step 9 produces a real Cloud Run services
> list you can screenshot for the demo video.

Estimated cost while idle: **$0/month** (scale to zero).
Under demo load (1 req/sec for 4 minutes): **<$0.10**.

## 0. Pre-flight (already verified)

- ✅ Python tests: `110 passed`
- ✅ Go tests: `27 passed`
- ✅ Docker Compose YAML validates
- ✅ Both Dockerfiles syntactically valid
- ✅ Live local pipeline: `state=CLOSED decision=ALLOW_SANDBOX tier=T0`

If you want to re-verify:

```bash
make test-py
cd services/action-broker-go && go test ./... && cd ../..
docker compose config   # validates docker-compose.yml
```

## 1. Install the gcloud CLI (10 min)

If you don't have it yet:

```bash
brew install --cask google-cloud-sdk
# OR: https://cloud.google.com/sdk/docs/install
exec $SHELL -l   # reload shell
gcloud --version
```

## 2. Authenticate (interactive — you must do this)

```bash
gcloud auth login
gcloud auth application-default login   # for the orchestrator's ADC
```

## 3. Pick a project

Everything in Chronos lives in a single project for this deployment:
**`annular-surf-439113-v6`**.

```bash
export PROJECT_ID=annular-surf-439113-v6
gcloud config set project $PROJECT_ID
```

That project hosts:

- The three GEAP agents (`chronos.detection_agent`, `chronos.debate_proposer`, `chronos.debate_auditor`)
- Cloud Run (orchestrator + broker + dashboard)
- Firestore (sessions, ledger, workflow, agent registry)
- Pub/Sub (incident ingress + DLQ)

If your project ID differs, change `PROJECT_ID` at the top of step 3; the
rest of the file uses `$PROJECT_ID` and will follow.

## 4. Enable APIs and provision the GEAP agents

```bash
gcloud services enable \
  aiplatform.googleapis.com \
  run.googleapis.com \
  firestore.googleapis.com \
  pubsub.googleapis.com \
  modelarmor.googleapis.com \
  cloudtrace.googleapis.com \
  secretmanager.googleapis.com
```

**Provision three GEAP agents.** Open the Gemini Enterprise Agent
Platform console:

- URL: https://console.cloud.google.com/agent-platform/agents
- Create agent → Agent ID `chronos.detection_agent` → output schema
  `FailureClassification` → paste `SYSTEM_PROMPT` from
  `apps/orchestrator/agents/detection.py`
- Create agent → Agent ID `chronos.debate_proposer` → output schema
  `ActionProposal` → paste `SYSTEM_PROMPT` from
  `apps/orchestrator/agents/proposer.py`
- Create agent → Agent ID `chronos.debate_auditor` → output schema
  `AuditCritique` → paste `SYSTEM_PROMPT` from
  `apps/orchestrator/agents/auditor.py`

Note the region you provisioned in (e.g. `us-central1` or `global`).

## 5. Service accounts + IAM (60 s)

```bash
for SA in chronos-orchestrator chronos-action-broker chronos-dashboard; do
  gcloud iam service-accounts create $SA --project=$PROJECT_ID
done

# Orchestrator: Vertex AI + Firestore + Pub/Sub
for ROLE in roles/aiplatform.user roles/datastore.user roles/pubsub.publisher roles/pubsub.subscriber roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:chronos-orchestrator@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="$ROLE"
done

# Broker: NO datastore write — only logging (zero-trust)
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:chronos-action-broker@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/logging.logWriter"

# Dashboard: read-only Datastore
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:chronos-dashboard@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/datastore.viewer"
```

## 6. Firestore + Pub/Sub (60 s)

```bash
gcloud firestore databases create --location=us-central1 --project=annular-surf-439113-v6
gcloud pubsub topics create chronos-incidents --project=annular-surf-439113-v6
gcloud pubsub topics create chronos-incidents-dlq --project=annular-surf-439113-v6
gcloud pubsub subscriptions create chronos-incidents-sub \
  --topic=chronos-incidents \
  --ack-deadline=60 \
  --message-retention-duration=7d \
  --project=annular-surf-439113-v6
```

## 7. Deploy the broker (fastest to deploy — verify it first)

```bash
export REGION=us-central1

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
cd ../..

export BROKER_URL=$(gcloud run services describe chronos-action-broker \
  --region=$REGION --project=$PROJECT_ID --format='value(status.url)')

# Let the orchestrator invoke the broker
gcloud run services add-iam-policy-binding chronos-action-broker \
  --region=$REGION --project=$PROJECT_ID \
  --member="serviceAccount:chronos-orchestrator@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

## 8. Deploy the orchestrator

```bash
cd /Users/oladimeji/chronos

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
    CHRONOS_BROKER_URL=$BROKER_URL

export ORCHESTRATOR_URL=$(gcloud run services describe chronos-orchestrator \
  --region=$REGION --project=$PROJECT_ID --format='value(status.url)')

# Wire Pub/Sub push subscription to the orchestrator
gcloud pubsub subscriptions update chronos-incidents-sub \
  --push-endpoint=$ORCHESTRATOR_URL/push \
  --project=$PROJECT_ID
```

## 9. Deploy the dashboard

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
cd ../..
```

## 10. Verify (and screenshot for the demo video)

```bash
gcloud run services list --region=$REGION --project=$PROJECT_ID
```

Expected output:

```
SERVICE                REGION       URL                                                ACTIVE
chronos-orchestrator   us-central1  https://chronos-orchestrator-xyz.a.run.app        yes
chronos-action-broker  us-central1  https://chronos-action-broker-xyz.a.run.app       yes
chronos-dashboard      us-central1  https://chronos-dashboard-xyz.a.run.app           yes
```

Smoke test:

```bash
curl $ORCHESTRATOR_URL/healthz
curl -X POST $ORCHESTRATOR_URL/api/incidents \
  -H "Content-Type: application/json" \
  -d @fixtures/incidents/schema-drift.json | jq
curl $ORCHESTRATOR_URL/api/ledger/verify
```

The last command should return `{"ok": true}`.

## 11. Tear down (so you don't get billed)

When the demo is over:

```bash
gcloud run services delete chronos-orchestrator chronos-action-broker chronos-dashboard \
  --region=$REGION --project=$PROJECT_ID --quiet
gcloud pubsub subscriptions delete chronos-incidents-sub --project=$PROJECT_ID --quiet
gcloud pubsub topics delete chronos-incidents chronos-incidents-dlq --project=$PROJECT_ID --quiet
# Optional — wipes Firestore
gcloud firestore databases delete --project=$PROJECT_ID --quiet
```

Total cost after teardown: $0.

## 12. If anything fails

| Symptom | Fix |
|---------|-----|
| `gcloud builds submit` slow first time | Normal — 3–5 min cold start |
| `GOOGLE_CLOUD_PROJECT not set` from orchestrator | You forgot step 4 or the env var didn't make it to the container |
| Orchestrator returns 500 on first request | Check logs: `gcloud run services logs read chronos-orchestrator --region=$REGION --project=$PROJECT_ID --limit=50` |
| `interactions.create` 404 | GEAP agent IDs don't match; check the console and update `AGENT_ID` constants in `apps/orchestrator/agents/*.py` |
| Model Armor 422 on a clean payload | Add `needs_human_review` triage; the heuristic should not flag routine schema-drift logs |

## What you get for the demo video

1. `gcloud run services list` — three rows, all ACTIVE
2. `gcloud run services logs read chronos-action-broker --limit=20` — JSON trace lines
3. The Cloud Run detail page showing revision history (1 deploy = 1 revision)
4. Live dashboard at `$ORCHESTRATOR_URL/` with the trace pipeline + ledger
5. A 90-second screen recording of the live `curl` chain

That's your "production on GCP" proof.