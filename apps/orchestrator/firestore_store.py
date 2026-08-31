"""Firestore-backed workflow store.

Production persistence for WorkflowRun records. Keyed by (incident_id, run_id).
Implements the same protocol as InMemoryWorkflowStore.
"""
from __future__ import annotations

import os

from contracts import WorkflowRun

from .workflow import WorkflowStore


class FirestoreWorkflowStore(WorkflowStore):
    COLLECTION = "chronos_workflow_runs"

    def __init__(self, db) -> None:  # db: google.cloud.firestore.Client
        self._db = db

    def load(self, incident_id: str, run_id: str) -> WorkflowRun | None:
        snap = (
            self._db.collection(self.COLLECTION)
            .document(incident_id)
            .collection(run_id)
            .document("run")
            .get()
        )
        if not snap.exists:
            return None
        return WorkflowRun.model_validate(snap.to_dict())

    def latest_for_incident(self, incident_id: str) -> WorkflowRun | None:
        runs = (
            self._db.collection(self.COLLECTION)
            .document(incident_id)
            .collections()
        )
        latest: WorkflowRun | None = None
        for sub in runs:
            doc = sub.document("run").get()
            if not doc.exists:
                continue
            run = WorkflowRun.model_validate(doc.to_dict())
            if latest is None or run.updated_at > latest.updated_at:
                latest = run
        return latest

    def save(self, run: WorkflowRun) -> None:
        self._db.collection(self.COLLECTION).document(run.incident_id).collection(run.run_id).document("run").set(run.model_dump())


def build_firestore_workflow_store():
    """Construct a FirestoreWorkflowStore, or ``None`` if no creds.

    Returns ``None`` in unit tests / local dev so the handler can fall back
    to the in-memory implementation.
    """
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        return None
    try:
        from google.cloud import firestore  # type: ignore
        client = firestore.Client(project=project)
        return FirestoreWorkflowStore(client)
    except Exception:
        return None