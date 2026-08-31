"""Fixture validation: each JSON fixture must conform to the Incident schema."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts import FailureClassification, Incident
from fixtures import load


def test_schema_drift_fixture_validates():
    p = load("schema-drift")
    inc = Incident.model_validate(p)
    assert inc.pipeline_id.startswith("pipe_")
    assert "schema" in inc.error_log.lower()


def test_api_timeout_fixture_validates():
    p = load("api-timeout")
    inc = Incident.model_validate(p)
    assert "timeout" in inc.error_log.lower() or "504" in inc.error_log


def test_heuristic_classifies_schema_drift():
    p = load("schema-drift")
    from apps.orchestrator.agents.detection import heuristic_classify
    c = heuristic_classify(p["incident_id"], p["error_log"])
    assert c.failure_type.value == "SCHEMA_CHANGE"


def test_heuristic_classifies_api_timeout():
    p = load("api-timeout")
    from apps.orchestrator.agents.detection import heuristic_classify
    c = heuristic_classify(p["incident_id"], p["error_log"])
    assert c.failure_type.value == "API_TIMEOUT"