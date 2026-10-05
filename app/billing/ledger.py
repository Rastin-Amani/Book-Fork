"""Credit ledger.

The wallet balance is a running total; ``credit_transactions`` is the audit
trail and source of truth. Every mutation writes a ledger entry with
balance-before/after and an idempotency ``reference``.
"""

from __future__ import annotations

from app.exceptions import InsufficientCreditsError
from app.observability.events import (
    CREDIT_ADJUSTED,
    CREDIT_CONSUMED,
    CREDIT_REFUNDED,
    CREDIT_RESERVED,
    emit,
)
from app.observability.metrics import metrics
from app.repositories.billing import CreditTransactionRepository, CreditWalletRepository
from app.schemas.billing import CreditTransaction, CreditWallet, TransactionType


class CreditLedger:
    """Reserve, settle, and adjust credits for a workspace wallet."""

    def __init__(
        self,
        wallets: CreditWalletRepository,
        transactions: CreditTransactionRepository,
        *,
        currency: str = "credits",
        token: str | None = None,
    ) -> None:
        self._wallets = wallets
        self._transactions = transactions
        self._currency = currency
        self._token = token

    async def ensure_wallet(self, workspace_id: str) -> CreditWallet:
        wallet = await self._wallets.get_for_workspace(
            workspace_id, self._currency, token=self._token
        )
        if wallet is not None:
            return wallet
        created = await self._wallets.create(
            {"workspace": workspace_id, "balance": 0.0, "currency": self._currency},
            token=self._token,
        )
        return created

    async def balance(self, workspace_id: str) -> float:
        wallet = await self.ensure_wallet(workspace_id)
        return wallet.balance

    async def reserve(
        self,
        workspace_id: str,
        amount: float,
        *,
        reference: str,
        job_id: str | None = None,
    ) -> CreditTransaction:
        return await self._apply(
            workspace_id,
            TransactionType.RESERVATION,
            -abs(amount),
            reference=reference,
            reason="Job credit reservation",
            job_id=job_id,
        )

    async def settle(
        self,
        workspace_id: str,
        *,
        reserved: float,
        actual: float,
        reference: str,
        job_id: str | None = None,
    ) -> list[CreditTransaction]:
        """Release the hold, then charge the actual usage."""
        released = await self._apply(
            workspace_id,
            TransactionType.REFUND,
            abs(reserved),
            reference=f"{reference}:release",
            reason="Release reservation",
            job_id=job_id,
        )
        consumed = await self._apply(
            workspace_id,
            TransactionType.CONSUMPTION,
            -abs(actual),
            reference=f"{reference}:consume",
            reason="Translation consumption",
            job_id=job_id,
        )
        return [released, consumed]

    async def refund(
        self,
        workspace_id: str,
        amount: float,
        *,
        reference: str,
        job_id: str | None = None,
    ) -> CreditTransaction:
        return await self._apply(
            workspace_id,
            TransactionType.REFUND,
            abs(amount),
            reference=reference,
            reason="Refund",
            job_id=job_id,
        )

    async def purchase(
        self, workspace_id: str, amount: float, *, reference: str
    ) -> CreditTransaction:
        return await self._apply(
            workspace_id,
            TransactionType.PURCHASE,
            abs(amount),
            reference=reference,
            reason="Credit purchase",
        )

    async def adjust(
        self,
        workspace_id: str,
        amount: float,
        *,
        reference: str,
        reason: str = "Adjustment",
    ) -> CreditTransaction:
        return await self._apply(
            workspace_id,
            TransactionType.ADJUSTMENT,
            amount,
            reference=reference,
            reason=reason,
            allow_negative=True,
        )

    async def _apply(
        self,
        workspace_id: str,
        tx_type: TransactionType,
        delta: float,
        *,
        reference: str,
        reason: str | None = None,
        job_id: str | None = None,
        created_by: str | None = None,
        allow_negative: bool = False,
    ) -> CreditTransaction:
        existing = await self._transactions.find_by_reference(reference, token=self._token)
        if existing is not None:
            return existing

        wallet = await self.ensure_wallet(workspace_id)
        new_balance = wallet.balance + delta
        if new_balance < 0 and not allow_negative:
            raise InsufficientCreditsError()

        # ponytail: read-modify-write; wrap in a PocketBase transaction /
        # optimistic lock if concurrent ledger writes become possible.
        await self._wallets.update(wallet.id, {"balance": new_balance}, token=self._token)
        transaction = await self._transactions.create(
            {
                "wallet": wallet.id,
                "type": tx_type.value,
                "amount": delta,
                "balance_before": wallet.balance,
                "balance_after": new_balance,
                "reason": reason,
                "job": job_id,
                "reference": reference,
                "created_by": created_by,
            },
            token=self._token,
        )
        self._observe(workspace_id, tx_type, delta, job_id)
        return transaction

    @staticmethod
    def _observe(
        workspace_id: str, tx_type: TransactionType, delta: float, job_id: str | None
    ) -> None:
        metrics.inc("book_fork_credits_total", abs(delta), type=tx_type.value)
        event = {
            TransactionType.RESERVATION: CREDIT_RESERVED,
            TransactionType.CONSUMPTION: CREDIT_CONSUMED,
            TransactionType.REFUND: CREDIT_REFUNDED,
        }.get(tx_type, CREDIT_ADJUSTED)
        emit(event, workspace_id=workspace_id, amount=delta, job_id=job_id)
