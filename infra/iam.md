# IAM — service accounts and least privilege

Chronos deploys two Cloud Run services, each with a dedicated service account
that has only the IAM roles it needs. No default service accounts are used.

## Service accounts

| SA                                   | Used by                | Roles                                                                                            |
|--------------------------------------|------------------------|--------------------------------------------------------------------------------------------------|
| `chronos-orchestrator@$PROJECT.iam`  | orchestrator Cloud Run | `roles/aiplatform.user`, `roles/datastore.user`, `roles/pubsub.publisher`, `roles/pubsub.subscriber` |
| `chronos-action-broker@$PROJECT.iam` | broker Cloud Run       | `roles/logging.logWriter` only                                                                   |
| `chronos-dashboard@$PROJECT.iam`     | dashboard (Streamlit)  | `roles/datastore.viewer` (read-only)                                                              |

## Why the broker has no Datastore write

The broker **never** writes to Firestore. Its only persistent state is in
memory (recent proposals for the dashboard). All ledger writes go through
the orchestrator's service account. If the broker's SA is compromised,
the attacker cannot tamper with the ledger — they can only return wrong
decisions, which are recorded in the ledger and auditable.

## Token exchange

The orchestrator mints a short-lived OIDC token to call the broker. The
broker validates the token against the project's JWKS. Tokens carry:

- `sub = chronos-orchestrator`
- `scope = chronos.broker`
- `aud = chronos-action-broker`
- `exp = now + 5m`

## Create the service accounts

```bash
PROJECT_ID=annular-surf-439113-v6
for SA in chronos-orchestrator chronos-action-broker chronos-dashboard; do
  gcloud iam service-accounts create $SA --project=$PROJECT_ID
done

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:chronos-orchestrator@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:chronos-orchestrator@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/datastore.user"

# broker gets no datastore write role — only logging
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:chronos-action-broker@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/logging.logWriter"

# dashboard read-only
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:chronos-dashboard@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/datastore.viewer"
```

## Deploy commands

```bash
gcloud run deploy chronos-orchestrator \
  --source . --platform managed --region us-central1 \
  --service-account chronos-orchestrator@$PROJECT_ID.iam.gserviceaccount.com \
  --min-instances 0 --max-instances 10 --memory 2Gi --cpu 2 \
  --allow-unauthenticated

gcloud run deploy chronos-action-broker \
  --source ./services/action-broker-go \
  --platform managed --region us-central1 \
  --service-account chronos-action-broker@$PROJECT_ID.iam.gserviceaccount.com \
  --min-instances 0 --max-instances 5 --memory 512Mi \
  --no-allow-unauthenticated
```

## Enable required APIs

```bash
gcloud services enable \
  aiplatform.googleapis.com \
  run.googleapis.com \
  firestore.googleapis.com \
  pubsub.googleapis.com \
  modelarmor.googleapis.com \
  cloudtrace.googleapis.com
```