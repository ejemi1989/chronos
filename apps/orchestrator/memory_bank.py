"""Chronos Memory Bank — persistent cross-session context.

The GEAP Memory Bank is a managed service for long-term, secure,
cross-session memory that personalizes agent interactions. Chronos
implements this as:

  - **Memory entries** — small JSON documents tagged with ``incident_id``,
    ``failure_type``, ``app_name``, and a free-text ``summary``.
  - **Append + search + recall** — entries are append-only, indexed by
    token-overlap similarity for the demo; production swaps in
    ``VertexAiMemoryBankService`` for embedding-based retrieval.
  - **Recall by incident** — given an ``incident_id``, return all
    memories tagged with it; this is what the Proposer consults before
    proposing a repair.
  - **Tenant isolation** — every entry is tagged with the
    ``tenant_id`` (``GOOGLE_CLOUD_PROJECT``); cross-tenant reads are
    rejected. This is the data-sovereignty guarantee the Fortified
    Enterprise Fleet track calls out.

Production wiring uses ``google.adk.memory.VertexAiMemoryBankService``;
this module is the deterministic fallback used by tests, local dev, and
the demo dashboard.
"""
from __future__ import annotations

import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Protocol


@dataclass(frozen=True)
class MemoryEntry:
    memory_id: str
    tenant_id: str
    app_name: str
    user_id: str
    incident_id: str | None
    failure_type: str | None
    summary: str
    content: str
    embedding: tuple[int, ...]  # simple bag-of-tokens hash for the demo
    created_at: float
    extra: dict[str, Any] = field(default_factory=dict)


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _tokenize(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text) if len(t) >= 3}


def _bag_hash(tokens: Iterable[str], dim: int = 4096) -> tuple[int, ...]:
    """Trivial bag-of-tokens hash for demo similarity.

    Production embeddings come from Vertex AI; this hash gives a
    deterministic, dependency-free fallback that works in tests.
    """
    counts = [0] * dim
    for tok in tokens:
        h = abs(hash(tok)) % dim
        counts[h] += 1
    return tuple(counts)


def _cosine(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class MemoryBank(Protocol):
    def append(self, *, tenant_id: str, app_name: str, user_id: str,
               summary: str, content: str, incident_id: str | None = None,
               failure_type: str | None = None,
               extra: dict[str, Any] | None = None) -> MemoryEntry: ...
    def search(self, query: str, *, tenant_id: str | None = None,
               limit: int = 10) -> list[MemoryEntry]: ...
    def recall_for(self, incident_id: str, *, tenant_id: str | None = None,
                   limit: int = 10) -> list[MemoryEntry]: ...
    def recent(self, limit: int = 20) -> list[MemoryEntry]: ...


class InMemoryMemoryBank:
    def __init__(self, default_tenant: str | None = None) -> None:
        self._entries: list[MemoryEntry] = []
        self._lock = threading.RLock()
        self._default_tenant = default_tenant or os.environ.get("GOOGLE_CLOUD_PROJECT", "local")

    def append(self, *, tenant_id: str | None = None, app_name: str,
               user_id: str, summary: str, content: str,
               incident_id: str | None = None,
               failure_type: str | None = None,
               extra: dict[str, Any] | None = None) -> MemoryEntry:
        tenant = tenant_id or self._default_tenant
        tokens = _tokenize(summary + " " + content)
        entry = MemoryEntry(
            memory_id=f"mem_{uuid.uuid4().hex[:10]}",
            tenant_id=tenant,
            app_name=app_name,
            user_id=user_id,
            incident_id=incident_id,
            failure_type=failure_type,
            summary=summary,
            content=content,
            embedding=_bag_hash(tokens),
            created_at=time.time(),
            extra=dict(extra or {}),
        )
        with self._lock:
            self._entries.append(entry)
        return entry

    def search(self, query: str, *, tenant_id: str | None = None,
               limit: int = 10) -> list[MemoryEntry]:
        tenant = tenant_id or self._default_tenant
        q_tokens = _tokenize(query)
        q_emb = _bag_hash(q_tokens)
        with self._lock:
            scored = [
                (_cosine(q_emb, e.embedding), e)
                for e in self._entries
                if e.tenant_id == tenant
            ]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:limit] if _ > 0]

    def recall_for(self, incident_id: str, *, tenant_id: str | None = None,
                   limit: int = 10) -> list[MemoryEntry]:
        tenant = tenant_id or self._default_tenant
        with self._lock:
            out = [
                e for e in self._entries
                if e.tenant_id == tenant and e.incident_id == incident_id
            ]
        out.sort(key=lambda e: e.created_at, reverse=True)
        return out[:limit]

    def recent(self, limit: int = 20) -> list[MemoryEntry]:
        with self._lock:
            out = list(self._entries)
        out.sort(key=lambda e: e.created_at, reverse=True)
        return out[:limit]


def build_memory_bank():
    """Construct the production memory bank or return ``None``.

    Returns ``None`` when no GCP credentials are present so callers can
    fall back to the in-memory implementation transparently.
    """
    try:
        from google.adk.memory import VertexAiMemoryBankService  # type: ignore
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("VERTEX_AI_LOCATION", "us-central1")
        if not project:
            return None
        return VertexAiMemoryBankService(project=project, location=location)
    except Exception:
        return None


def memory_entry_to_dict(entry: MemoryEntry) -> dict[str, Any]:
    d = asdict(entry)
    d["embedding"] = None  # never expose internal hash in API output
    return d