"""Agent Registry tests — discoverability, versioning, deprecation."""
from __future__ import annotations

import pytest

from apps.orchestrator.agent_registry import (
    AgentCard,
    CHRONOS_CATALOG,
    InMemoryAgentRegistry,
    make_agent_record,
)


def test_canonical_catalog_has_four_agents():
    """Chronos ships with 4 agents: detection, proposer, auditor, broker."""
    assert len(CCHRONOS_CATALOG if False else CHRONOS_CATALOG) == 4
    ids = {r.agent_id for r in CHRONOS_CATALOG}
    assert ids == {
        "chronos.detection_agent",
        "chronos.debate_proposer",
        "chronos.debate_auditor",
        "chronos.action_broker",
    }


def test_registry_seeded_with_canonical_catalog():
    reg = InMemoryAgentRegistry()
    assert len(reg.list()) == 4


def test_registry_filter_by_capability():
    reg = InMemoryAgentRegistry()
    hits = reg.list(capability="remediation-proposal")
    assert len(hits) == 1
    assert hits[0].agent_id == "chronos.debate_proposer"


def test_registry_filter_by_tier():
    reg = InMemoryAgentRegistry()
    hits = reg.list(tier="T1_SAFE")
    assert len(hits) == 1
    assert hits[0].agent_id == "chronos.action_broker"


def test_registry_filter_by_owner():
    reg = InMemoryAgentRegistry()
    hits = reg.list(owner="chronos-core")
    assert len(hits) == 4


def test_registry_get_latest_version():
    reg = InMemoryAgentRegistry()
    rec = reg.get("chronos.detection_agent")
    assert rec is not None
    assert rec.version == 1
    assert "failure-classification" in rec.card.capabilities


def test_registry_get_specific_version():
    reg = InMemoryAgentRegistry()
    rec = reg.get("chronos.detection_agent", version=1)
    assert rec is not None
    assert rec.version == 1


def test_registry_versions_returns_all():
    reg = InMemoryAgentRegistry()
    rec = make_agent_record(
        agent_id="chronos.detection_agent",
        card=AgentCard(
            name="detection_agent",
            version="2",
            description="Updated detection agent with heuristic fallback.",
            capabilities=["failure-classification", "log-analysis", "needs-human-review"],
target="gemini-3.5-flash",
            output_schema="FailureClassification",
        ),
        owner="chronos-core",
        tier="T0_SANDBOX",
    )
    reg.publish(rec)
    versions = reg.versions("chronos.detection_agent")
    assert [v.version for v in versions] == [1, 2]
    assert versions[-1].card.description.endswith("heuristic fallback.")


def test_registry_publish_idempotent_on_same_content():
    reg = InMemoryAgentRegistry()
    rec = reg.get("chronos.detection_agent")
    again = reg.publish(rec)
    # Same content → no new version
    assert again.version == rec.version


def test_registry_deprecate():
    reg = InMemoryAgentRegistry()
    ok = reg.deprecate("chronos.detection_agent", 1)
    assert ok is True
    listed = reg.list()
    assert all(r.agent_id != "chronos.detection_agent" for r in listed)


def test_registry_content_hash_stable():
    rec = reg_seeded()
    rec2 = reg_seeded()
    assert rec.content_hash == rec2.content_hash


def reg_seeded():
    return make_agent_record(
        agent_id="test.agent",
        card=AgentCard(
            name="agent", version="1", description="d",
            capabilities=["x"], target="gemini-3.5-flash",
        ),
        owner="team", tier="T0_SANDBOX",
    )