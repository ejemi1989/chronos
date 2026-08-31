"""Fixture loader: read JSON fixtures and submit them to the orchestrator."""
from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).parent


def load(name: str) -> dict:
    return json.loads((FIXTURES / "incidents" / f"{name}.json").read_text())


if __name__ == "__main__":
    import httpx
    for name in ("schema-drift", "api-timeout"):
        payload = load(name)
        r = httpx.post("http://localhost:8080/api/incidents", json=payload, timeout=8.0)
        print(name, r.status_code, r.text[:200])