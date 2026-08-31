"""GEAP Interactions integration tests.

The agents target provisioned agents on Gemini Enterprise Agent Platform
(``client.interactions.create(agent="...", input="...", response_format=...)``).
Without GCP credentials these tests use ``build_offline_pipeline()`` which
routes through ``OfflineInteractionsClient`` for deterministic responses.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from apps.orchestrator.agents import auditor, detection, proposer
from apps.orchestrator.controller import (
    ControllerResult,
    Pipeline,
    build_offline_pipeline,
    build_pipeline,
)
from apps.orchestrator.interactions_agent import (
    InteractionsAgent,
    InteractionsError,
    OfflineInteractionsClient,
    _extract_output_text,
    _extract_steps,
    _normalize,
    _OfflineResponse,
    offline_responder_from_factory,
    offline_responder_from_text,
)


def test_build_pipeline_returns_interactions_agents():
    """Production wiring: pipeline of three InteractionsAgent objects."""
    p = build_pipeline()
    assert isinstance(p, Pipeline)
    for agent, expected_id in zip(
        [p.detection_agent, p.proposer_agent, p.auditor_agent],
        [
            "chronos.detection_agent",
            "chronos.debate_proposer",
            "chronos.debate_auditor",
        ],
    ):
        assert isinstance(agent, InteractionsAgent)
        assert agent.agent_id == expected_id


def test_agents_use_provisioned_agent_ids():
    """No agent uses a base model name; GEAP requires provisioned agents."""
    expected = {
        "chronos.detection_agent": "FailureClassification",
        "chronos.debate_proposer": "ActionProposal",
        "chronos.debate_auditor": "AuditCritique",
    }
    builders = (detection.build, proposer.build, auditor.build)
    for builder in builders:
        agent = builder()
        assert agent.agent_id in expected, f"{agent.agent_id} not a provisioned agent"
        assert agent.response_schema.__name__ == expected[agent.agent_id]


def test_agents_have_no_tools():
    """Tool-poisoning guard: agents must not receive callable tools."""
    for builder in (detection.build, proposer.build, auditor.build):
        agent = builder()
        tools = getattr(agent, "tools", None) or []
        assert tools == [], f"{agent.agent_id} holds tools: {tools}"


def test_agents_have_strict_output_schema():
    """Model Armor layer 1: every agent constrains output via Pydantic."""
    for builder in (detection.build, proposer.build, auditor.build):
        agent = builder()
        assert agent.response_schema is not None


@pytest.mark.asyncio
async def test_offline_pipeline_runs_end_to_end():
    """Offline pipeline completes 1 round with auditor acceptance."""
    p = build_offline_pipeline(incident_id="inc_aaaaaa")
    result = await asyncio.wait_for(
        _run_async(p),
        timeout=5.0,
    )
    assert isinstance(result, ControllerResult)
    assert result.accepted is True
    assert result.rounds == 1


@pytest.mark.asyncio
async def test_offline_pipeline_emits_three_agent_calls():
    """Each agent in the pipeline must be invoked exactly once on accept."""
    counts = {"chronos.detection_agent": 0, "chronos.debate_proposer": 0, "chronos.debate_auditor": 0}

    class CountingClient:
        def __init__(self):
            self.det_text = (
                '{"incident_id":"inc_aaaaaa","failure_type":"SCHEMA_CHANGE",'
                '"severity":"HIGH","impact":["downstream"],'
                '"root_cause":"schema drift observed in upstream payload"}'
            )
            self.prop_text = (
                '{"proposal_id":"prop_000001","incident_id":"inc_aaaaaa",'
                '"proposed_by":"chronos.debate_proposer","round":1,'
                '"action":"ROLLBACK_SCHEMA","target":"prod.pipeline",'
                '"reversible":true,"financial_impact":0,'
                '"rollback":"automatic","success_criteria":"ok"}'
            )
            self.crit_text = (
                '{"proposal_id":"prop_000001","accept":true,'
                '"counterarguments":[],"recommended_tier":null,'
                '"reason":"plan looks good"}'
            )

        def create(self, **kwargs):
            aid = kwargs.get("agent", "")
            counts[aid] = counts.get(aid, 0) + 1
            return _OfflineResponse(
                output_text={
                    "chronos.detection_agent": self.det_text,
                    "chronos.debate_proposer": self.prop_text,
                    "chronos.debate_auditor": self.crit_text,
                }[aid]
            )

    from contracts import (
        AuditCritique, ActionProposal, FailureClassification,
    )
    client = CountingClient()
    pipeline = Pipeline(
        detection_agent=InteractionsAgent(
            agent_id="chronos.detection_agent",
            response_schema=FailureClassification, client=client,
        ),
        proposer_agent=InteractionsAgent(
            agent_id="chronos.debate_proposer",
            response_schema=ActionProposal, client=client,
        ),
        auditor_agent=InteractionsAgent(
            agent_id="chronos.debate_auditor",
            response_schema=AuditCritique, client=client,
        ),
    )
    result = await _run_async(pipeline, timeout_s=5.0)
    assert result.accepted is True
    assert counts["chronos.detection_agent"] == 1
    assert counts["chronos.debate_proposer"] == 1
    assert counts["chronos.debate_auditor"] == 1


@pytest.mark.asyncio
async def test_production_client_requires_project_env(monkeypatch):
    """Without GOOGLE_CLOUD_PROJECT the production client fails fast."""
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    agent = InteractionsAgent(agent_id="chronos.detection_agent")
    with pytest.raises(InteractionsError) as excinfo:
        agent.run("hello")
    assert "GOOGLE_CLOUD_PROJECT" in str(excinfo.value)


def test_extract_output_text_from_steps():
    """``_extract_output_text`` walks steps correctly when no accessor."""
    resp = _OfflineResponse(output_text="hello")
    assert _extract_output_text(resp) == "hello"


def test_normalize_parses_pydantic_schema():
    """``_normalize`` validates the response against the schema."""
    from contracts import FailureClassification
    resp = _OfflineResponse(output_text=(
        '{"incident_id":"inc_aaaaaa","failure_type":"SCHEMA_CHANGE",'
        '"severity":"HIGH","impact":["downstream"],'
        '"root_cause":"schema drift observed in upstream payload"}'
    ))
    out = _normalize(resp, "chronos.detection_agent", FailureClassification)
    assert isinstance(out.parsed, FailureClassification)
    assert out.parsed.failure_type.value == "SCHEMA_CHANGE"


def test_normalize_raises_on_schema_mismatch():
    """Schema mismatch raises InteractionsError."""
    from contracts import FailureClassification
    resp = _OfflineResponse(output_text="not valid json at all")
    with pytest.raises(InteractionsError) as excinfo:
        _normalize(resp, "chronos.detection_agent", FailureClassification)
    assert "does not match" in str(excinfo.value)


def test_extract_steps_handles_dict_and_object():
    """``_extract_steps`` works with both dict and object steps."""
    class ObjResp:
        output_text = "x"
        steps = [{"type": "model_output", "content": [{"type": "text", "text": "x"}]}]
        usage = {}
        id = "abc"
    steps = _extract_steps(ObjResp())
    assert len(steps) == 1
    assert steps[0]["type"] == "model_output"


async def _run_async(pipeline, timeout_s: float = 5.0):
    """Run the offline pipeline with a short timeout for tests."""
    from apps.orchestrator.controller import run_incident
    return await run_incident(
        "schema drift observed in upstream payload",
        pipeline=pipeline,
        timeout_s=timeout_s,
    )