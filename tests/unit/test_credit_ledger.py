"""Credit ledger audit trail and idempotency."""

from __future__ import annotations

import pytest
from app.billing.ledger import CreditLedger
from app.exceptions import InsufficientCreditsError
from app.repositories.billing import CreditTransactionRepository, CreditWalletRepository


def _ledger(pb) -> CreditLedger:
    return CreditLedger(CreditWalletRepository(pb), CreditTransactionRepository(pb))


async def test_purchase_reserve_settle(pb, fake_pb) -> None:
    ws = fake_pb.seed("workspaces", {"name": "W", "slug": "w", "owner": "u1"})
    ledger = _ledger(pb)

    await ledger.purchase(ws["id"], 100, reference="purchase-1")
    assert await ledger.balance(ws["id"]) == 100

    tx = await ledger.reserve(ws["id"], 10, reference="job-1:reserve")
    assert tx.amount == -10
    assert tx.balance_before == 100
    assert tx.balance_after == 90

    await ledger.settle(ws["id"], reserved=10, actual=7, reference="job-1")
    assert await ledger.balance(ws["id"]) == 93


async def test_insufficient_credits_rejected(pb, fake_pb) -> None:
    ws = fake_pb.seed("workspaces", {"name": "W", "slug": "w", "owner": "u1"})
    ledger = _ledger(pb)
    await ledger.purchase(ws["id"], 5, reference="p")
    with pytest.raises(InsufficientCreditsError):
        await ledger.reserve(ws["id"], 10, reference="too-much")


async def test_idempotent_by_reference(pb, fake_pb) -> None:
    ws = fake_pb.seed("workspaces", {"name": "W", "slug": "w", "owner": "u1"})
    ledger = _ledger(pb)
    await ledger.purchase(ws["id"], 100, reference="p")
    await ledger.reserve(ws["id"], 10, reference="dup")
    await ledger.reserve(ws["id"], 10, reference="dup")
    assert await ledger.balance(ws["id"]) == 90
    transactions = fake_pb.collections["credit_transactions"]
    assert len(transactions) == 2  # purchase + one reservation


async def test_adjustment_can_go_negative(pb, fake_pb) -> None:
    ws = fake_pb.seed("workspaces", {"name": "W", "slug": "w", "owner": "u1"})
    ledger = _ledger(pb)
    tx = await ledger.adjust(ws["id"], -20, reference="adj", reason="correction")
    assert tx.balance_after == -20
