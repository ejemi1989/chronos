"""Chronos Agent Registry — first-class catalog of agent cards.

The GEAP Agent Registry is a managed catalog where organizations publish,
version, and discover approved agents. Chronos implements this as a small,
deterministic catalog of the agents it knows about:

  - Each agent has a stable ``agent_id``, a monotonically increasing
    ``version``, a ``card`` (A2A-compatible), and a list of ``capabilities``
    with input/output schemas.
  - Discovery is filterable by capability, owner, and tier.
  - Versions are immutable — publishing the same ``agent_id`` twice with the
    same content is a no-op; publishing with different content creates a
    new version.
  - The catalog is persisted to Firestore in production; an in-memory
    implementation is used for tests / local dev.

The same catalog format is reused by the broker's action registry
(services/action-broker-go/internal/registry) so a single registry lookup
can resolve both agents and actions.
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol


@dataclass(frozen=True)
class AgentCard:
    """A2A-compatible agent card."""
    name: str
    version: str
    description: str
    capabilities: list[str]
    target: str
    output_schema: str | None = None
    endpoint: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentRecord:
    """One entry in the registry catalog."""
    agent_id: str
    version: int
    card: AgentCard
    owner: str
    tier: str  # T0_SANDBOX, T1_SAFE, T2_REVERSIBLE, T3_DESTRUCTIVE
    published_at: float
    content_hash: str
    deprecated: bool = False


def _hash_card(card: AgentCard) -> str:
    raw = "|".join([
        card.name, card.version, card.description,
        ",".join(sorted(card.capabilities)),
        card.target, card.output_schema or "",
        card.endpoint or "",
    ]).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def make_agent_record(
    agent_id: str,
    card: AgentCard,
    owner: str,
    tier: str,
    *,
    deprecated: bool = False,
) -> AgentRecord:
    return AgentRecord(
        agent_id=agent_id,
        version=int(card.version),
        card=card,
        owner=owner,
        tier=tier,
        published_at=time.time(),
        content_hash=_hash_card(card),
        deprecated=deprecated,
    )


# Canonical Chronos agent catalog. Published at every deploy; agents are
# discoverable by capability (e.g. "failure-classification", "policy-review",
# "trace-replay").
CHRONOS_CATALOG: list[AgentRecord] = [
    make_agent_record(
        agent_id="chronos.detection_agent",
        card=AgentCard(
            name="detection_agent",
            version="1",
            description="Classifies pipeline failure logs into FailureClassification.",
            capabilities=["failure-classification", "log-analysis", "needs-human-review"],
            target="gemini-3.5-flash",
            output_schema="FailureClassification",
            endpoint="/agents/detection_agent",
        ),
        owner="chronos-core",
        tier="T0_SANDBOX",
    ),
    make_agent_record(
        agent_id="chronos.debate_proposer",
        card=AgentCard(
            name="debate_proposer",
            version="1",
            description="Proposes repair strategies as ActionProposal; never holds tools.",
            capabilities=["remediation-proposal", "rollback-planning", "policy-aware"],
            target="gemini-3.5-flash",
            output_schema="ActionProposal",
            endpoint="/agents/debate_proposer",
        ),
        owner="chronos-core",
        tier="T0_SANDBOX",
    ),
    make_agent_record(
        agent_id="chronos.debate_auditor",
        card=AgentCard(
            name="debate_auditor",
            version="1",
            description="Attacks proposals with concrete counterarguments; never upgrades tier.",
            capabilities=["remediation-review", "counterargument-generation", "tier-downgrade"],
            target="gemini-3.5-flash",
            output_schema="AuditCritique",
            endpoint="/agents/debate_auditor",
        ),
        owner="chronos-core",
        tier="T0_SANDBOX",
    ),
    make_agent_record(
        agent_id="chronos.action_broker",
        card=AgentCard(
            name="action_broker",
            version="1",
            description="Deterministic A2A broker; T3 destructive actions structurally unreachable.",
            capabilities=["policy-evaluation", "allow-list-check", "tier-enforcement"],
            target="n/a",
            endpoint="https://chronos-action-broker.run.app/a2a/v1/invoke",
        ),
        owner="chronos-core",
        tier="T1_SAFE",
    ),
]


class AgentRegistry(Protocol):
    def list(self, capability: str | None = None, owner: str | None = None,
             tier: str | None = None) -> list[AgentRecord]: ...
    def get(self, agent_id: str, version: int | None = None) -> AgentRecord | None: ...
    def versions(self, agent_id: str) -> list[AgentRecord]: ...
    def publish(self, record: AgentRecord) -> AgentRecord: ...
    def deprecate(self, agent_id: str, version: int) -> bool: ...


class InMemoryAgentRegistry:
    def __init__(self, seed: list[AgentRecord] | None = None) -> None:
        self._by_id: dict[str, list[AgentRecord]] = {}
        self._lock = threading.RLock()
        for rec in (seed or CHRONOS_CATALOG):
            self.publish(rec)

    def list(self, capability: str | None = None, owner: str | None = None,
             tier: str | None = None) -> list[AgentRecord]:
        with self._lock:
            all_records = [r for versions in self._by_id.values() for r in versions]
        out = []
        for r in all_records:
            if r.deprecated:
                continue
            if capability and capability not in r.card.capabilities:
                continue
            if owner and r.owner != owner:
                continue
            if tier and r.tier != tier:
                continue
            out.append(r)
        return sorted(out, key=lambda r: r.agent_id)

    def get(self, agent_id: str, version: int | None = None) -> AgentRecord | None:
        with self._lock:
            versions = self._by_id.get(agent_id, [])
            if not versions:
                return None
            if version is None:
                return max(versions, key=lambda r: r.version)
            for r in versions:
                if r.version == version:
                    return r
        return None

    def versions(self, agent_id: str) -> list[AgentRecord]:
        with self._lock:
            return sorted(self._by_id.get(agent_id, []), key=lambda r: r.version)

    def publish(self, record: AgentRecord) -> AgentRecord:
        with self._lock:
            versions = self._by_id.setdefault(record.agent_id, [])
            for existing in versions:
                if existing.content_hash == record.content_hash:
                    return existing
            record_dict = record.__dict__.copy()
            new_version = (max((r.version for r in versions), default=0)) + 1
            record_dict["version"] = new_version
            new_record = AgentRecord(**record_dict)
            versions.append(new_record)
        return new_record

    def deprecate(self, agent_id: str, version: int) -> bool:
        with self._lock:
            for r in self._by_id.get(agent_id, []):
                if r.version == version:
                    object.__setattr__(r, "deprecated", True)
                    return True
        return False


def build_firestore_agent_registry():
    """Firestore-backed agent registry for production.

    Returns ``None`` if no GCP project is configured; callers should fall
    back to ``InMemoryAgentRegistry`` so tests and local dev still work.
    """
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        return None
    try:
        from google.cloud import firestore  # type: ignore
        db = firestore.Client(project=project)
        return _FirestoreAgentRegistry(db)
    except Exception:
        return None


class _FirestoreAgentRegistry:
    COLLECTION = "chronos_agent_registry"

    def __init__(self, db) -> None:
        self._db = db
        self._local = InMemoryAgentRegistry()  # write-through cache

    def list(self, capability=None, owner=None, tier=None):
        return self._local.list(capability=capability, owner=owner, tier=tier)

    def get(self, agent_id, version=None):
        return self._local.get(agent_id, version)

    def versions(self, agent_id):
        return self._local.versions(agent_id)

    def publish(self, record):
        persisted = self._local.publish(record)
        self._db.collection(self.COLLECTION).document(record.agent_id).collection(
            str(persisted.version)
        ).document("card").set(persisted.__dict__)
        return persisted

    def deprecate(self, agent_id, version):
        ok = self._local.deprecate(agent_id, version)
        if ok:
            self._db.collection(self.COLLECTION).document(agent_id).collection(
                str(version)
            ).document("card").update({"deprecated": True})
        return ok