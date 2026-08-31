"""Hash chain primitives.

We hash the canonical JSON of each entry's fields EXCEPT ``entry_hash``
itself, which is the only excluded field. The chain is anchored by the
previous entry's ``entry_hash``; the genesis entry uses 64 zero bytes.
"""
from __future__ import annotations

import hashlib

from .canonical import canonical_dumps

GENESIS_PREV = "0" * 64
_HASH_FIELDS = ("seq", "timestamp", "actor", "action_type", "proposal_id", "decision", "payload", "previous_hash")


def compute_hash(entry: dict) -> str:
    """Compute the SHA-256 hash of an entry, omitting ``entry_hash`` itself."""
    sub = {k: entry[k] for k in _HASH_FIELDS if k in entry}
    return hashlib.sha256(canonical_dumps(sub).encode("utf-8")).hexdigest()