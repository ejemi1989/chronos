"""Vertex AI Memory Bank service.

Chronos uses long-horizon memory to recall similar past incidents and
debate transcripts so DetectionAgent can classify faster and the Proposer
can propose from precedent.
"""
from __future__ import annotations

import os


def build_memory_service():
    """Return an ADK memory service, or ``None`` if unavailable.
    """
    try:
        from google.adk.memory import VertexAiMemoryBankService, InMemoryMemoryService  # noqa: F401
    except ImportError:
        return None

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("VERTEX_AI_LOCATION", "us-central1")
    if not project:
        return None
    try:
        return VertexAiMemoryBankService(project=project, location=location)
    except Exception:
        return None


def store_incident_memory(incident: dict, classification: dict) -> None:
    """Add a (incident, classification) pair to the memory bank.

    Used at the end of each run so future runs can search by similarity.
    """
    try:
        from google.adk.memory import VertexAiMemoryBankService
    except ImportError:
        return
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        return
    try:
        svc = VertexAiMemoryBankService(project=project)
        svc.add_event(
            app_name="chronos",
            user_id="chronos",
            content=f"Incident {incident['incident_id']}: {classification['failure_type']} - {classification['root_cause']}",
        )
    except Exception:
        pass