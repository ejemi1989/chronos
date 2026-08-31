"""Pub/Sub handler tests with in-memory transport + idempotency."""
from __future__ import annotations

import pytest

from contracts import WorkflowState
from orchestrator.pubsub_handler import (
    HandlerConfig,
    handle_message,
)
from orchestrator.workflow import InMemoryWorkflowStore, is_terminal


class FakePubSub:
    def __init__(self):
        self.published = []
        self.acked = []
        self.nacked = []

    def pull(self, subscription, max_messages=1):
        return []

    def ack(self, subscription, ack_id):
        self.acked.append((subscription, ack_id))

    def nack(self, subscription, ack_id):
        self.nacked.append((subscription, ack_id))

    def publish(self, topic, data):
        self.published.append((topic, data))


def _msg():
    return {
        "ack_id": "ack-1",
        "data": {
            "incident_id": "inc_abcdef",
            "pipeline_id": "pipe_xyz1",
            "error_log": "boom",
            "context": {},
            "detected_at": 0.0,
            "raw_telemetry": "boom",
        },
    }


@pytest.mark.asyncio
async def test_idempotent_skip_for_terminal_run():
    store = InMemoryWorkflowStore()
    pubsub = FakePubSub()
    # First message → BLOCKED via DLQ path (no real runner wired).
    run1 = await handle_message(_msg(), store=store, pubsub=pubsub)
    assert run1.state == WorkflowState.BLOCKED

    # Second message → same incident returns the same run, no new DLQ publish.
    dlq_before = len(pubsub.published)
    run2 = await handle_message(_msg(), store=store, pubsub=pubsub)
    assert run2.run_id == run1.run_id
    assert run2.state == WorkflowState.BLOCKED
    assert len(pubsub.published) == dlq_before


@pytest.mark.asyncio
async def test_dlq_publishes_on_schema_reject():
    store = InMemoryWorkflowStore()
    pubsub = FakePubSub()
    await handle_message(_msg(), store=store, pubsub=pubsub)
    topics = [t for t, _ in pubsub.published]
    assert "chronos-incidents-dlq" in topics