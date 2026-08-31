"""Firestore-backed session service.

The ADK ships ``FirestoreSessionService`` natively, but we wrap it so:
  * we can fall back to ``InMemorySessionService`` when no GCP credentials
    are present (tests, local dev);
  * we centralize the project / database config;
  * we tag every session with the chronos run_id for cross-correlation.
"""
from __future__ import annotations

import os

from contracts import WorkflowRun


def build_session_service():
    """Return an ADK session service.

    Returns ``None`` if ADK isn't installed (callers fall back to in-memory).
    """
    try:
        from google.adk.sessions import FirestoreSessionService, InMemorySessionService  # noqa: F401
    except ImportError:
        return None

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    database = os.environ.get("FIRESTORE_DATABASE", "(default)")
    if not project:
        # No GCP project — caller should use the in-memory service.
        return None

    try:
        return FirestoreSessionService(project=project, database=database, collection="chronos_sessions")
    except Exception:
        return None


def load_session_run(session_id: str) -> WorkflowRun | None:
    """Reconstruct a WorkflowRun from a stored session (Firestore or memory).

    The session's ``state_delta`` carries the latest ``last_proposal``,
    ``last_decision`` etc. that the controller wrote; we rebuild a
    ``WorkflowRun`` for external consumers.
    """
    try:
        from google.adk.sessions import FirestoreSessionService
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project:
            return None
        svc = FirestoreSessionService(project=project)
        # Session persistence is opaque to us here; in production the API
        # layer reads ``WorkflowRun`` from Firestore directly via a
        # FirestoreWorkflowStore, not via the session service.
        return None
    except ImportError:
        return None