"""Chronos Interactions Agent — wraps the GEAP Interactions API.

The Gemini Interactions API is the modern, server-managed way to call
provisioned agents on Gemini Enterprise Agent Platform (GEAP). Per the
skill spec:

  - Use ``google-genai >= 2.3.0`` (verified: 2.20.0).
  - Target a **provisioned agent** via ``agent="<AGENT_ID>"`` — base
    model calls are not supported on GEAP.
  - Pass turn-scoped parameters (``tools``, ``system_instruction``,
    ``generation_config``) on every interaction.
  - Read ``output_text`` (the convenience accessor that combines the
    trailing ``model_output`` steps) instead of hand-walking
    ``steps[-1].content[0].text`` — that breaks when the trailing step
    is a ``function_call`` or ``thought``.
  - For structured output, pass ``response_format=<Pydantic model>``.
    The Interactions API validates the JSON against the schema and
    returns the parsed text in ``output_text``.

Chronos wraps this with a thin ``InteractionsAgent`` class that:
  1. Holds an ``agent_id`` (the GEAP-provisioned agent path).
  2. Holds an optional ``response_format`` Pydantic model — the agent
     emits JSON that matches the schema.
  3. Exposes ``run(text)`` which returns the parsed Pydantic instance,
     or raises ``InteractionsError``.
  4. Honors a deterministic offline mode for tests and local dev
     (no GCP credentials needed): ``OfflineInteractionsClient`` returns
     canned responses from a fixture file or a callable.

Production wiring: ``GOOGLE_GENAI_USE_VERTEXAI=true`` plus
``GOOGLE_CLOUD_PROJECT=<id>`` plus ``VERTEX_AI_LOCATION=global``. The
Chronos agent IDs (``chronos.detection_agent``, ``chronos.debate_proposer``,
``chronos.debate_auditor``) are provisioned once in the GEAP console.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from pydantic import BaseModel

log = logging.getLogger("chronos.interactions")


class InteractionsError(Exception):
    """Raised when the Interactions API returns an error or the response
    cannot be parsed into the declared schema."""


class InteractionsClient(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


@dataclass
class InteractionResult:
    """A normalized result from the Interactions API."""
    agent_id: str
    output_text: str
    parsed: BaseModel | None
    interaction_id: str | None
    steps: list[dict[str, Any]]
    usage: dict[str, Any]


class InteractionsAgent:
    """Wraps a GEAP-provisioned agent behind a Pydantic schema.

    ``run(text)`` returns ``InteractionResult`` whose ``.parsed`` is the
    schema-validated Pydantic instance (when ``response_schema`` is set).
    The raw ``output_text`` is always available.
    """

    def __init__(
        self,
        agent_id: str,
        *,
        response_schema: type[BaseModel] | None = None,
        system_instruction: str | None = None,
        tools: list[Any] | None = None,
        generation_config: dict[str, Any] | None = None,
        client: InteractionsClient | None = None,
        previous_interaction_id: str | None = None,
        store: bool = True,
    ) -> None:
        self.agent_id = agent_id
        self.response_schema = response_schema
        self.system_instruction = system_instruction
        self.tools = tools or []
        self.generation_config = generation_config or {}
        self._client = client
        self.previous_interaction_id = previous_interaction_id
        self.store = store

    @property
    def client(self) -> InteractionsClient:
        if self._client is None:
            self._client = _build_default_client()
        return self._client

    def run(self, text: str) -> InteractionResult:
        """Send a single-turn interaction and return the result."""
        kwargs: dict[str, Any] = {
            "agent": self.agent_id,
            "input": text,
            "store": self.store,
        }
        if self.previous_interaction_id:
            kwargs["previous_interaction_id"] = self.previous_interaction_id
        # Per skill spec: turn-scoped parameters must be passed each turn.
        if self.system_instruction:
            kwargs["system_instruction"] = self.system_instruction
        if self.tools:
            kwargs["tools"] = self.tools
        if self.generation_config:
            kwargs["generation_config"] = self.generation_config
        if self.response_schema is not None:
            kwargs["response_format"] = self.response_schema

        log.info("interactions.create agent=%s schema=%s",
                 self.agent_id,
                 self.response_schema.__name__ if self.response_schema else None)

        response = self.client.create(**kwargs)
        return _normalize(response, self.agent_id, self.response_schema)

    async def run_async(self, text: str) -> InteractionResult:
        """Async wrapper — calls ``run`` in a thread since the SDK is sync.

        The Interactions SDK returns a synchronous object; we use
        ``asyncio.to_thread`` so callers can ``await`` without blocking
        the event loop.
        """
        import asyncio
        return await asyncio.to_thread(self.run, text)


def _build_default_client() -> InteractionsClient:
    """Build the production client using ADC + Vertex AI."""
    try:
        from google import genai  # type: ignore
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("VERTEX_AI_LOCATION", "global")
        if not project:
            raise InteractionsError(
                "GOOGLE_CLOUD_PROJECT not set; cannot build production Interactions client"
            )
        # Per skill: GOOGL_GENAI_USE_VERTEXAI=true routes to Vertex/GEAP.
        os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
        return genai.Client(vertexai=True, project=project, location=location)
    except ImportError as exc:  # pragma: no cover
        raise InteractionsError(
            "google-genai not installed; run `pip install google-genai>=2.3.0`"
        ) from exc


def _extract_output_text(response: Any) -> str:
    """Read the convenience accessor when present; fall back to step walking."""
    out = getattr(response, "output_text", None)
    if out:
        return out
    steps = getattr(response, "steps", None) or []
    parts: list[str] = []
    for step in steps:
        step_type = getattr(step, "type", None) or (step.get("type") if isinstance(step, dict) else None)
        if step_type != "model_output":
            continue
        content = getattr(step, "content", None) or (step.get("content") if isinstance(step, dict) else None) or []
        for c in content:
            text = getattr(c, "text", None) or (c.get("text") if isinstance(c, dict) else None)
            if text:
                parts.append(text)
    return "".join(parts)


def _extract_steps(response: Any) -> list[dict[str, Any]]:
    steps = getattr(response, "steps", None)
    if not steps:
        return []
    out: list[dict[str, Any]] = []
    for step in steps:
        if isinstance(step, dict):
            out.append(step)
        elif hasattr(step, "model_dump"):
            out.append(step.model_dump(exclude_none=True))
        else:
            out.append({"type": getattr(step, "type", None)})
    return out


def _extract_usage(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return usage
    return usage.model_dump() if hasattr(usage, "model_dump") else {}


def _normalize(
    response: Any,
    agent_id: str,
    schema: type[BaseModel] | None,
) -> InteractionResult:
    text = _extract_output_text(response)
    parsed: BaseModel | None = None
    if schema is not None and text:
        try:
            parsed = schema.model_validate_json(text)
        except Exception as exc:
            raise InteractionsError(
                f"agent {agent_id} returned text that does not match "
                f"{schema.__name__}: {exc}\ntext={text[:300]}"
            ) from exc
    return InteractionResult(
        agent_id=agent_id,
        output_text=text,
        parsed=parsed,
        interaction_id=getattr(response, "id", None),
        steps=_extract_steps(response),
        usage=_extract_usage(response),
    )


# ---------- Offline client for tests and local dev ----------


class OfflineInteractionsClient:
    """Deterministic client used by tests and the local-dev fallback.

    Routes each ``agent=...`` to a callable that produces the canned
    response. The callable receives the kwargs (including ``input``) and
    must return an object with at least ``output_text`` / ``steps``.
    """

    def __init__(self, responders: dict[str, Callable[[dict[str, Any]], Any]]) -> None:
        self._responders = responders

    def create(self, **kwargs: Any) -> Any:
        agent_id = kwargs.get("agent", "")
        responder = self._responders.get(agent_id)
        if responder is None:
            raise InteractionsError(f"no offline responder for agent {agent_id!r}")
        return responder(kwargs)


@dataclass
class _OfflineResponse:
    output_text: str
    id: str = "offline-interaction-0001"
    steps: list[dict[str, Any]] = None
    usage: dict[str, Any] = None

    def __post_init__(self) -> None:
        self.steps = self.steps or [{"type": "model_output",
                                     "content": [{"type": "text", "text": self.output_text}]}]
        self.usage = self.usage or {"total_input_tokens": 1, "total_output_tokens": 1, "total_tokens": 2}


def offline_responder_from_text(text: str) -> Callable[[dict[str, Any]], _OfflineResponse]:
    """Build a responder that always returns the same canned text."""
    def _r(_kwargs: dict[str, Any]) -> _OfflineResponse:
        return _OfflineResponse(output_text=text)
    return _r


def offline_responder_from_factory(
    factory: Callable[[dict[str, Any]], dict[str, Any] | str],
) -> Callable[[dict[str, Any]], _OfflineResponse]:
    """Build a responder that calls ``factory(kwargs)`` and JSON-encodes."""
    def _r(kwargs: dict[str, Any]) -> _OfflineResponse:
        out = factory(kwargs)
        if isinstance(out, str):
            return _OfflineResponse(output_text=out)
        return _OfflineResponse(output_text=json.dumps(out))
    return _r