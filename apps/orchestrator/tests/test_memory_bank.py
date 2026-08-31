"""Memory Bank tests — append, search, recall, tenant isolation."""
from __future__ import annotations

import pytest

from apps.orchestrator.memory_bank import (
    InMemoryMemoryBank,
    _cosine,
    _tokenize,
    memory_entry_to_dict,
)


def test_tokenize_drops_short_and_punctuation():
    assert _tokenize("Hello, world! a b schema") == {"hello", "world", "schema"}


def test_cosine_zero_for_empty():
    assert _cosine((), (1, 2)) == 0.0
    assert _cosine((0, 0), (0, 0)) == 0.0


def test_cosine_positive_for_overlap():
    a = (1, 1, 0)
    b = (1, 1, 0)
    assert _cosine(a, b) == pytest.approx(1.0)


def test_append_returns_entry_with_embedding():
    mb = InMemoryMemoryBank(default_tenant="t1")
    e = mb.append(
        app_name="chronos", user_id="u1",
        summary="schema drift detected",
        content="upstream payload added a column",
        incident_id="inc_aaaaaa",
        failure_type="SCHEMA_CHANGE",
    )
    assert e.memory_id.startswith("mem_")
    assert e.tenant_id == "t1"
    assert e.failure_type == "SCHEMA_CHANGE"
    assert len(e.embedding) == 4096


def test_search_finds_similar_entry():
    mb = InMemoryMemoryBank(default_tenant="t1")
    mb.append(
        app_name="chronos", user_id="u1",
        summary="schema drift in upstream payload",
        content="unexpected column addition",
    )
    hits = mb.search("schema drift unexpected column")
    assert len(hits) >= 1


def test_search_skips_unrelated():
    mb = InMemoryMemoryBank(default_tenant="t1")
    mb.append(
        app_name="chronos", user_id="u1",
        summary="auth token rotated",
        content="jwt credentials refreshed",
    )
    hits = mb.search("schema drift column addition")
    assert hits == []


def test_recall_for_incident():
    mb = InMemoryMemoryBank(default_tenant="t1")
    mb.append(
        app_name="chronos", user_id="u1",
        summary="first try", content="x", incident_id="inc_aaaaaa",
    )
    mb.append(
        app_name="chronos", user_id="u1",
        summary="second try", content="y", incident_id="inc_aaaaaa",
    )
    mb.append(
        app_name="chronos", user_id="u1",
        summary="other incident", content="z", incident_id="inc_bbbbbb",
    )
    out = mb.recall_for("inc_aaaaaa")
    assert len(out) == 2
    assert all(e.incident_id == "inc_aaaaaa" for e in out)


def test_tenant_isolation():
    """Memories in tenant A are invisible to tenant B."""
    mb = InMemoryMemoryBank(default_tenant="default")
    mb.append(
        app_name="chronos", user_id="u1",
        summary="tenant A only", content="secret",
        tenant_id="tenant-A",
    )
    assert mb.search("secret", tenant_id="tenant-A")
    assert mb.search("secret", tenant_id="tenant-B") == []


def test_recent_orders_newest_first():
    mb = InMemoryMemoryBank()
    mb.append(app_name="c", user_id="u", summary="first", content="x")
    mb.append(app_name="c", user_id="u", summary="second", content="x")
    mb.append(app_name="c", user_id="u", summary="third", content="x")
    out = mb.recent()
    assert [e.summary for e in out] == ["third", "second", "first"]


def test_memory_entry_to_dict_hides_embedding():
    mb = InMemoryMemoryBank()
    e = mb.append(app_name="c", user_id="u", summary="x", content="y")
    d = memory_entry_to_dict(e)
    assert d["embedding"] is None
    assert d["memory_id"] == e.memory_id
    assert d["summary"] == "x"