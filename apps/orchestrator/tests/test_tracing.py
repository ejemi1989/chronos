"""Tracing tests — span emission + reasoning chain ordering."""
from __future__ import annotations

import asyncio

from apps.orchestrator.tracing import get_recent_spans, reset, span


def test_span_lifecycle():
    reset()
    with span("test.span", parent=None) as s:
        s.attributes["k"] = "v"
    spans = get_recent_spans()
    assert len(spans) == 1
    assert spans[0]["name"] == "test.span"
    assert spans[0]["status"] == "OK"
    assert spans[0]["attributes"]["k"] == "v"
    assert spans[0]["end_ns"] is not None


def test_nested_spans_chain():
    reset()
    with span("outer") as outer:
        with span("inner", parent=outer) as inner:
            pass
    spans = list(reversed(get_recent_spans(10)))
    # Newest first
    assert spans[0]["name"] == "inner"
    assert spans[0]["parent_span_id"] == outer.span_id
    assert spans[1]["name"] == "outer"
    assert spans[1]["parent_span_id"] is None


def test_span_error_marks_status():
    reset()
    try:
        with span("boom") as s:
            raise RuntimeError("kaboom")
    except RuntimeError:
        pass
    spans = get_recent_spans()
    assert spans[0]["status"] == "ERROR"
    assert "kaboom" in spans[0]["attributes"]["error"]


def test_reset_clears_buffer():
    reset()
    with span("a"):
        pass
    assert len(get_recent_spans()) == 1
    reset()
    assert get_recent_spans() == []