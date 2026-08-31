"""A2A client — orchestrator → Action Broker."""
from __future__ import annotations

import httpx
from contracts import (
    ActionProposal,
    ActionTier,
    BrokerDecision,
    BrokerVerdict,
)


class BrokerUnavailable(Exception):
    """Raised when the broker can't be reached."""


class BrokerError(Exception):
    """Raised when the broker returns a non-decision error."""


_BROKER_URL = "http://localhost:8080"


async def submit_proposal(
    proposal: ActionProposal,
    bearer_token: str,
    *,
    base_url: str = _BROKER_URL,
    timeout: float = 4.0,
) -> BrokerVerdict:
    """Submit an ActionProposal to the broker and return its verdict.

    Note: tier mapping is structural — the broker independently enforces
    the tier, so even if we mislabel here it still blocks T3.
    """
    payload = {
        "proposal_id": proposal.proposal_id,
        "action_type": proposal.action_type,
        "tier": proposal.tier.value,
        "version": 1,
    }
    headers = {"Authorization": f"Bearer {bearer_token}"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{base_url}/a2a/v1/invoke", json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise BrokerUnavailable(str(exc)) from exc

    if resp.status_code == 401:
        raise BrokerError("unauthorized")
    if resp.status_code >= 500:
        raise BrokerUnavailable(resp.text)
    if resp.status_code >= 400:
        raise BrokerError(resp.text)

    body = resp.json()
    return BrokerVerdict(
        proposal_id=body["proposal_id"],
        decision=BrokerDecision(body["decision"]),
        reason=body.get("reason", ""),
    )


def derive_default_bearer() -> str:
    """Stub for local dev: returns a syntactically valid JWT.

    In production this is replaced with an OIDC token fetched from the IdP.
    """
    import base64
    import json

    header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": "orchestrator", "scopes": ["chronos.broker"]}).encode()
    ).rstrip(b"=")
    return f"{header.decode()}.{payload.decode()}."