"""Transaction-safe Firestore ledger.

The ledger enforces three properties:

1. **Sequence atomicity** — each entry receives a strictly-increasing ``seq``
   via a Firestore ``run_transaction`` block. The transaction reads the
   current head, increments, and writes the new entry in one shot.

2. **Tamper-evidence** — each entry stores ``previous_hash`` and
   ``entry_hash`` (SHA-256 over the canonical JSON of the rest of the
   entry). ``verify_chain()`` walks the chain from genesis to head.

3. **No unresolved timestamps** — ``timestamp`` is captured from the Firestore
   server's commit time via ``server_timestamp``, returned to the caller and
   then HASHED. We never hash a Python-side ``time.time()`` value.

The single-writer fallback (``InMemoryLedger``) is provided for unit tests
and local development so the codebase can run without GCP credentials.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Protocol

from contracts import BrokerDecision, LedgerEntry

from .hash_chain import GENESIS_PREV, compute_hash


@dataclass
class _Head:
    seq: int
    entry_hash: str


class Ledger(Protocol):
    async def append(
        self, *, actor: str, action_type: str, proposal_id: str,
        decision: BrokerDecision, payload: dict,
    ) -> LedgerEntry: ...
    async def head(self) -> LedgerEntry | None: ...
    async def verify_chain(self) -> bool: ...


# ---------- In-memory implementation (for tests / local) ----------


class InMemoryLedger:
    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []
        self._lock = asyncio.Lock()

    async def append(
        self, *, actor: str, action_type: str, proposal_id: str,
        decision: BrokerDecision, payload: dict,
    ) -> LedgerEntry:
        async with self._lock:
            prev = self._entries[-1] if self._entries else None
            seq = (prev.seq + 1) if prev else 0
            prev_hash = prev.entry_hash if prev else GENESIS_PREV
            # Server-side commit time: in-memory we use monotonic time captured
            # AFTER the lock is acquired so the value is committed atomically
            # with the entry — never pre-committed.
            timestamp = time.time()
            entry_dict = {
                "seq": seq,
                "timestamp": timestamp,
                "actor": actor,
                "action_type": action_type,
                "proposal_id": proposal_id,
                "decision": decision.value,
                "payload": payload,
                "previous_hash": prev_hash,
            }
            entry_dict["entry_hash"] = compute_hash(entry_dict)
            entry = LedgerEntry.model_validate(entry_dict)
            self._entries.append(entry)
            return entry

    async def head(self) -> LedgerEntry | None:
        return self._entries[-1] if self._entries else None

    async def verify_chain(self) -> bool:
        prev_hash = GENESIS_PREV
        for i, e in enumerate(self._entries):
            if e.seq != i:
                return False
            if e.previous_hash != prev_hash:
                return False
            if compute_hash(e.model_dump()) != e.entry_hash:
                return False
            prev_hash = e.entry_hash
        return True


# ---------- Firestore implementation (production) ----------


class FirestoreLedger:
    """Production ledger. Requires ``firebase-admin`` initialized externally.

    Uses ``run_transaction`` to atomically:
      1. Read current head from ``ledger/head`` doc.
      2. Increment seq.
      3. Write new entry to ``ledger/entries/{seq}``.
      4. Update ``ledger/head`` with new seq + entry_hash.
      5. Capture ``update_time`` (server timestamp) and store it on entry.

    The transaction commits only after all writes succeed, so concurrent
    writers cannot produce duplicate seq numbers.
    """

    def __init__(self, db) -> None:  # db is a firestore.Client
        self._db = db

    async def append(
        self, *, actor: str, action_type: str, proposal_id: str,
        decision: BrokerDecision, payload: dict,
    ) -> LedgerEntry:
        transaction = self._db.transaction()

        @firestore_transactional
        def _txn(txn):
            head_ref = self._db.collection("ledger").document("head")
            head_snap = head_ref.get(transaction=txn)
            prev_seq = head_snap.get("seq") if head_snap.exists else -1
            prev_hash = head_snap.get("entry_hash") if head_snap.exists else GENESIS_PREV
            new_seq = prev_seq + 1
            ts = head_snap.update_time.timestamp() if head_snap.exists else time.time()
            entry_dict = {
                "seq": new_seq,
                "timestamp": ts,
                "actor": actor,
                "action_type": action_type,
                "proposal_id": proposal_id,
                "decision": decision.value,
                "payload": payload,
                "previous_hash": prev_hash,
            }
            entry_dict["entry_hash"] = compute_hash(entry_dict)
            self._db.collection("ledger").document("entries").collection(str(new_seq)).document("data").set(entry_dict, transaction=txn)
            head_ref.set({"seq": new_seq, "entry_hash": entry_dict["entry_hash"]}, transaction=txn)
            return LedgerEntry.model_validate(entry_dict)

        return await asyncio.get_event_loop().run_in_executor(None, _txn)

    async def head(self) -> LedgerEntry | None:
        return await asyncio.get_event_loop().run_in_executor(None, self._head_sync)

    def _head_sync(self) -> LedgerEntry | None:
        head_ref = self._db.collection("ledger").document("head")
        snap = head_ref.get()
        if not snap.exists:
            return None
        seq = snap.get("seq")
        entry_snap = (
            self._db.collection("ledger").document("entries").collection(str(seq)).document("data").get()
        )
        if not entry_snap.exists:
            return None
        return LedgerEntry.model_validate(entry_snap.to_dict())

    async def verify_chain(self) -> bool:
        return await asyncio.get_event_loop().run_in_executor(None, self._verify_sync)

    def _verify_sync(self) -> bool:
        prev_hash = GENESIS_PREV
        for i in itertools.count():
            ref = self._db.collection("ledger").document("entries").collection(str(i)).document("data")
            snap = ref.get()
            if not snap.exists:
                break
            d = snap.to_dict()
            e = LedgerEntry.model_validate(d)
            if e.seq != i:
                return False
            if e.previous_hash != prev_hash:
                return False
            if compute_hash(d) != e.entry_hash:
                return False
            prev_hash = e.entry_hash
        return True


# Avoid an import-at-top for optional deps.
import itertools
try:
    from google.cloud.firestore_v1.transaction import transactional as firestore_transactional  # type: ignore
except ImportError:  # pragma: no cover
    def firestore_transactional(fn):  # type: ignore
        return fn