"""Chronos orchestrator — GEAP Interactions agents, controller, ledger.

Importing this package does NOT eagerly import google.genai — that
happens inside ``InteractionsAgent.client`` on first call. This lets
contract and pure-logic tests run without the GenAI SDK installed.
"""
from .client import FirestoreLedger, InMemoryLedger, Ledger
from .controller import (
    ControllerResult,
    NeedsHumanReview,
    Pipeline,
    RoundLimitExceeded,
    SchemaReject,
    dispatch_to_broker,
)
from .hash_chain import compute_hash
from .canonical import canonical_dumps

__all__ = [
    "ControllerResult",
    "FirestoreLedger",
    "InMemoryLedger",
    "Ledger",
    "NeedsHumanReview",
    "Pipeline",
    "RoundLimitExceeded",
    "SchemaReject",
    "canonical_dumps",
    "compute_hash",
    "dispatch_to_broker",
]


def __getattr__(name: str):
    if name in {
        "build_pipeline", "build_offline_pipeline", "run_incident",
        "_derive_tier", "_tier_rank",
    }:
        from . import controller as _controller
        return getattr(_controller, name)
    raise AttributeError(name)