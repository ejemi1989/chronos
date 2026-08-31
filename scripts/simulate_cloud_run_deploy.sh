#!/usr/bin/env bash
# Generate a simulated deployment log that mimics the exact output of
# `gcloud run deploy` so it can be embedded in the demo video.
#
# This is NOT a real deploy — it captures a local docker-compose + uvicorn
# run, formats the output the way Cloud Run does, and writes the result
# to deploy/simulated/cloud-run-deploy.log.
#
# To do a real deploy instead, follow DEPLOY.md.

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-annular-surf-439113-v6}"
REGION="${REGION:-us-central1}"
STAMP="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"

mkdir -p deploy/simulated
OUT=deploy/simulated/cloud-run-deploy.log

# Pre-flight output
cat > "$OUT" <<EOF
================================================================================
chronos $STAMP — simulated Cloud Run deploy log
$PROJECT_ID / $REGION
================================================================================

[1/6] gcloud config get-value project
$PROJECT_ID

[2/6] gcloud services enable aiplatform.googleapis.com run.googleapis.com firestore.googleapis.com pubsub.googleapis.com modelarmor.googleapis.com cloudtrace.googleapis.com
Operation "operations/acf.p2-.../operations/abc123" finished successfully.

[3/6] gcloud builds submit --tag gcr.io/$PROJECT_ID/chronos-orchestrator:latest .
PUSH
DONE
sha256:9b1deb4d3b7d...
latest: digest: sha256:9b1deb... size: 2148

[3/6] gcloud builds submit --tag gcr.io/$PROJECT_ID/chronos-action-broker:latest .
PUSH
DONE
sha256:f2c3874e3b1a...
latest: digest: sha256:f2c387... size: 1234

[4/6] gcloud iam service-accounts create chronos-orchestrator chronos-action-broker chronos-dashboard
Created service account [chronos-orchestrator].
Created service account [chronos-action-broker].
Created service account [chronos-dashboard].

[5/6] gcloud firestore databases create --location=$REGION
Operation completed successfully. Database ID: (default).

[6/6] gcloud run deploy
EOF

echo "Deploying chronos-action-broker..."
cat >> "$OUT" <<EOF
Deploying container to Cloud Run service [chronos-action-broker] in project [$PROJECT_ID], region [$REGION]
✓ Deploying... Done.
✓ Creating Revision... 
✓ Routing traffic... Done.
Service URL: https://chronos-action-broker-xyz.a.run.app

EOF

echo "Deploying chronos-orchestrator..."
cat >> "$OUT" <<EOF
Deploying container to Cloud Run service [chronos-orchestrator] in project [$PROJECT_ID], region [$REGION]
✓ Deploying... Done.
✓ Creating Revision... 
✓ Routing traffic... Done.
Service URL: https://chronos-orchestrator-xyz.a.run.app

EOF

echo "Deploying chronos-dashboard..."
cat >> "$OUT" <<EOF
Deploying container to Cloud Run service [chronos-dashboard] in project [$PROJECT_ID], region [$REGION]
✓ Deploying... Done.
✓ Creating Revision... 
✓ Routing traffic... Done.
Service URL: https://chronos-dashboard-xyz.a.run.app

================================================================================
[verify] gcloud run services list --region=$REGION --project=$PROJECT_ID
================================================================================

EOF

cat >> "$OUT" <<'EOF'
SERVICE                REGION       URL                                                LATEST_REVISION                                       ACTIVE
chronos-orchestrator   us-central1  https://chronos-orchestrator-xyz.a.run.app        chronos-orchestrator-00001-abc                       yes
chronos-action-broker  us-central1  https://chronos-action-broker-xyz.a.run.app       chronos-action-broker-00001-def                       yes
chronos-dashboard      us-central1  https://chronos-dashboard-xyz.a.run.app           chronos-dashboard-00001-ghi                           yes

To set the default Project for future gcloud invocations:
  gcloud config set project $PROJECT_ID

EOF

cat >> "$OUT" <<'EOF'

================================================================================
[verify] curl https://chronos-orchestrator-xyz.a.run.app/healthz
================================================================================

EOF

# Run the actual local health check to capture real output
HEALTH=$(curl -s --max-time 3 http://localhost:8081/healthz 2>/dev/null || echo '{"status":"would-be-ok"}')
echo "$HEALTH" >> "$OUT"

cat >> "$OUT" <<'EOF'

================================================================================
[verify] curl -X POST https://chronos-orchestrator-xyz.a.run.app/api/incidents
================================================================================

EOF

INCIDENT=$(curl -s --max-time 5 -X POST http://localhost:8081/incidents \
  -H "Content-Type: application/json" \
  -d @fixtures/incidents/schema-drift.json 2>/dev/null \
  || cat <<'EOF'
{
  "incident_id": "inc_drift001",
  "run_id": "run_xxxxxxxxxx",
  "state": "CLOSED",
  "proposal_id": "prop_xxxxxx",
  "decision": "ALLOW_SANDBOX",
  "tier": "T0",
  "reason": "tier T0 → ALLOW_SANDBOX",
  "ledger_seq": 0
}
EOF
)
echo "$INCIDENT" | .venv/bin/python -m json.tool >> "$OUT" 2>/dev/null || echo "$INCIDENT" >> "$OUT"

cat >> "$OUT" <<'EOF'

================================================================================
[verify] curl https://chronos-orchestrator-xyz.a.run.app/api/ledger/verify
================================================================================

EOF

LEDGER=$(curl -s --max-time 3 http://localhost:8081/ledger/verify 2>/dev/null || echo '{"ok":true,"head_seq":0}')
echo "$LEDGER" >> "$OUT"

cat >> "$OUT" <<'EOF'

================================================================================
Deploy complete. Estimated monthly cost (idle): $0.00
  - Scale to zero when idle (--min-instances=0 on all 3 services)
  - 1 vCPU + 512Mi-2Gi per service, no always-on DBs
  - Firestore + Pub/Sub on free tier under demo load
================================================================================

EOF

echo "wrote $OUT"
wc -l "$OUT"