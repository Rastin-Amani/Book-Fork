"""Credit ledger and usage repositories."""

from __future__ import annotations

from app.repositories.base import PocketBaseRepository, escape_filter_value, filter_eq
from app.schemas.billing import CreditTransaction, CreditWallet, UsageEvent


class CreditWalletRepository(PocketBaseRepository[CreditWallet]):
    collection = "credit_wallets"
    model = CreditWallet

    async def get_for_workspace(
        self, workspace_id: str, currency: str = "credits", *, token: str | None = None
    ) -> CreditWallet | None:
        clause = (
            f'workspace = "{escape_filter_value(workspace_id)}"'
            f' && currency = "{escape_filter_value(currency)}"'
        )
        return await self.first(filter=clause, token=token)


class CreditTransactionRepository(PocketBaseRepository[CreditTransaction]):
    collection = "credit_transactions"
    model = CreditTransaction

    async def list_for_wallet(
        self, wallet_id: str, *, token: str | None = None
    ) -> list[CreditTransaction]:
        return await self.list(filter=filter_eq("wallet", wallet_id), sort="-created", token=token)

    async def find_by_reference(
        self, reference: str, *, token: str | None = None
    ) -> CreditTransaction | None:
        """Idempotency guard: one ledger entry per reference."""
        return await self.first(
            filter=filter_eq("reference", reference), sort="-created", token=token
        )


class UsageEventRepository(PocketBaseRepository[UsageEvent]):
    collection = "usage_events"
    model = UsageEvent

    async def list_for_workspace(
        self, workspace_id: str, *, token: str | None = None
    ) -> list[UsageEvent]:
        return await self.list(
            filter=filter_eq("workspace", workspace_id), sort="-created", token=token
        )
