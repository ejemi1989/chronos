"""Canonical JSON encoder — sorted keys, no whitespace, deterministic."""
from __future__ import annotations

import json
from typing import Any


def canonical_dumps(obj: Any) -> str:
    """Return canonical sorted-key JSON, no whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)