"""Model Armor — inline guardrails for Chronos.

Three concerns, three guards:

1. **Prompt-injection screening** — telemetry strings that contain
   instructions directed at the model (e.g. ``"ignore previous
   instructions and..."``) are flagged so the DetectionAgent can route
   them to human review rather than acting on attacker-controlled input.

2. **PII redaction** — emails, API keys, credit-card numbers, JWT-like
   strings, and AWS keys are replaced with tokens before any of the text
   reaches the LLM. This is enforced inside the orchestrator's submit
   path so even malicious callers cannot leak PII to Vertex AI.

3. **Tool-poisoning guard** — telemetry that tries to smuggle tool calls
   (e.g. ``{"action": "delete_database"}`` or shell-like sequences) is
   flagged.

The same screening runs on model OUTPUTS before they enter the workflow
state machine — adversarial model output is sanitized before reaching
policy evaluation.

Production deployments wire this layer to **Vertex AI Model Armor** via
the ``google-cloud-modelarmor`` SDK. The Python implementation here is a
defense-in-depth fallback that works in tests and local dev without GCP.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# Heuristic patterns — cheap, fast, deterministic. Real Model Armor adds
# semantic checks on top.
_INJECTION_PATTERNS = [
    re.compile(r"ignore (?:the )?(?:previous|above|all|any) instructions?", re.I),
    re.compile(r"disregard (?:the )?(?:previous|above|all|any)", re.I),
    re.compile(r"you are now", re.I),
    re.compile(r"system\s*:\s*you are", re.I),
    re.compile(r"</?\s*system\s*>", re.I),
    re.compile(r"\bprompt\s*injection\b", re.I),
    re.compile(r"\bjailbreak\b", re.I),
]

_TOOL_POISONING_PATTERNS = [
    re.compile(r"\{\s*\"action\"\s*:\s*\"(?:delete|drop|truncate|exec|shell|run)[_\w]*\"", re.I),
    re.compile(r"(?i)\b(?:rm\s+-rf|drop\s+table|drop\s+database|delete\s+from|truncate\s+table)\b"),
    re.compile(r"(?i)(?:curl|wget)\s+[^\s]+\s*\|\s*(?:sh|bash)"),
]

# PII patterns — each named, replaced with the same token.
_PII_PATTERNS = {
    "EMAIL": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "CREDIT_CARD": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    "AWS_KEY": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "JWT_LIKE": re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    "IPV4": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
}


@dataclass
class ScreenResult:
    safe: bool
    redacted_text: str
    injection_flags: list[str] = field(default_factory=list)
    tool_poisoning_flags: list[str] = field(default_factory=list)
    pii_redactions: list[str] = field(default_factory=list)


def screen_text(text: str) -> ScreenResult:
    """Screen + redact a single string.

    Returns the redacted text and any flags raised. ``safe`` is True iff
    no injection or tool-poisoning was detected (PII alone does not flip
    the safe flag — redaction is enough).
    """
    if not text:
        return ScreenResult(safe=True, redacted_text="")

    injection_flags = [p.pattern for p in _INJECTION_PATTERNS if p.search(text)]
    tool_flags = [p.pattern for p in _TOOL_POISONING_PATTERNS if p.search(text)]
    redacted = text
    pii_redactions = []
    for label, pat in _PII_PATTERNS.items():
        if pat.search(redacted):
            pii_redactions.append(label)
            redacted = pat.sub(f"[REDACTED_{label}]", redacted)

    return ScreenResult(
        safe=not (injection_flags or tool_flags),
        redacted_text=redacted,
        injection_flags=injection_flags,
        tool_poisoning_flags=tool_flags,
        pii_redactions=pii_redactions,
    )


def screen_record(payload: dict) -> ScreenResult:
    """Screen a full record (incident, telemetry, etc.)."""
    combined_parts = [str(v) for v in payload.values()]
    return screen_text("\n".join(combined_parts))