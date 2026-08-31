"""Pytest config: make ``apps/`` and ``services/`` importable as top-level packages.

This lets tests do ``from orchestrator import ...`` and ``from contracts import ...``
without packaging Chronos as a wheel.
"""
import os
import sys

ROOT = os.path.dirname(__file__)
for sub in ("apps", "contracts"):
    p = os.path.join(ROOT, sub)
    if p not in sys.path:
        sys.path.insert(0, p)