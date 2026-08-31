"""Ledger tests — chain integrity, concurrent writers, tamper detection."""
from __future__ import annotations

import asyncio
import pytest

from contracts import BrokerDecision
from orchestrator import InMemoryLedger, compute_hash
from orchestrator.hash_chain import GENESIS_PREV


@pytest.mark.asyncio
async def test_append_assigns_strictly_increasing_seq():
    led = InMemoryLedger()
    e0 = await led.append(actor="broker", action_type="cache.flush",
                          proposal_id="p1", decision=BrokerDecision.ALLOW_SANDBOX,
                          payload={})
    e1 = await led.append(actor="broker", action_type="queue.drain",
                          proposal_id="p2", decision=BrokerDecision.REQUIRE_APPROVAL,
                          payload={})
    assert (e0.seq, e1.seq) == (0, 1)
    assert e1.previous_hash == e0.entry_hash


@pytest.mark.asyncio
async def test_verify_chain_clean():
    led = InMemoryLedger()
    for i in range(5):
        await led.append(actor="a", action_type="cache.flush", proposal_id=f"p{i}",
                         decision=BrokerDecision.ALLOW_SANDBOX, payload={"i": i})
    assert await led.verify_chain() is True


@pytest.mark.asyncio
async def test_verify_chain_detects_tamper():
    led = InMemoryLedger()
    for i in range(3):
        await led.append(actor="a", action_type="cache.flush", proposal_id=f"p{i}",
                         decision=BrokerDecision.ALLOW_SANDBOX, payload={"i": i})
    # Mutate an entry payload post-hoc — chain must reject.
    led._entries[1].payload = {"i": 999}  # type: ignore[index]
    assert await led.verify_chain() is False


@pytest.mark.asyncio
async def test_concurrent_writers_no_duplicate_seq():
    led = InMemoryLedger()

    async def writer(i: int):
        await led.append(actor="a", action_type="cache.flush",
                         proposal_id=f"p{i}", decision=BrokerDecision.ALLOW_SANDBOX,
                         payload={"i": i})

    await asyncio.gather(*[writer(i) for i in range(20)])
    seqs = [e.seq for e in led._entries]
    assert seqs == sorted(seqs) and len(set(seqs)) == 20
    assert await led.verify_chain() is True


@pytest.mark.asyncio
async def test_genesis_uses_zero_hash():
    led = InMemoryLedger()
    e = await led.append(actor="a", action_type="cache.flush", proposal_id="p0",
                         decision=BrokerDecision.ALLOW_SANDBOX, payload={})
    assert e.previous_hash == GENESIS_PREV
    assert e.entry_hash == compute_hash(e.model_dump())