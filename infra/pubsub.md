# Pub/Sub topology

Chronos uses two Pub/Sub topics to ingress incidents and route unrecoverable
failures to a dead-letter queue.

## Topics

| Topic                        | Direction | Producer            | Consumer              | Purpose                                  |
|------------------------------|-----------|---------------------|-----------------------|------------------------------------------|
| `chronos-incidents`          | inbound   | upstream pipelines   | orchestrator (push)   | New incidents arrive here                |
| `chronos-incidents-dlq`      | outbound  | orchestrator        | human ops / PagerDuty | Unrecoverable failures land here         |

## Subscriptions

- `chronos-incidents-sub` (push → orchestrator FastAPI)
  - ack deadline: 60 seconds
  - message retention: 7 days
  - retry policy: exponential backoff, max 5 attempts before DLQ
- `chronos-incidents-dlq-sub` (pull → ops)
  - ack deadline: 600 seconds
  - no retry — ops investigates manually

## Replay command

Re-driving a DLQ message replays the incident against the orchestrator with
the same `run_id`, so the workflow store's idempotency check short-circuits
if the run already reached `CLOSED` or `BLOCKED`.

```bash
gcloud pubsub subscriptions pull chronos-incidents-dlq-sub \
  --project=$PROJECT_ID --limit=10 --format=json
```

The orchestrator publishes the deterministic replay payload via the
`replay_command()` helper in `apps/orchestrator/workflow.py`.

## Retry semantics

| Failure                              | Action                                         |
|--------------------------------------|------------------------------------------------|
| SchemaReject (LLM output invalid)    | DLQ + terminal BLOCKED run                     |
| NeedsHumanReview                     | DLQ + terminal BLOCKED run                     |
| RoundLimitExceeded                   | DLQ + terminal BLOCKED run                     |
| Broker 5xx                           | NACK, retry up to 5 attempts, then DLQ         |
| Broker 401/403                       | DLQ immediately (config error)                 |
| Transient Firestore write failure    | NACK, exponential backoff                      |