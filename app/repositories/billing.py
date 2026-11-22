"""Billing repositories: invoices, webhook events, free-allowance claims.

Invoice writes happen through the service credential because clients must never
create or mutate payment records. Reads for the customer UI use the requesting
user's token so the collection rules enforce workspace ownership.
"""

from __future__ import annotations

from app.exceptions import ConflictError, ValidationError
from app.repositories.base import PocketBaseRepository, filter_eq
from app.schemas.billing import BillingEvent, BillingFreeClaim, BillingInvoice

_OPEN_STATUSES = ("pending", "awaiting_payment", "partially_paid", "review")


def _in_statuses(field: str, statuses: tuple[str, ...]) -> str:
    return " || ".join(f'{field} = "{status}"' for status in statuses)


class BillingInvoiceRepository(PocketBaseRepository[BillingInvoice]):
    collection = "billing_invoices"
    model = BillingInvoice

    async def list_for_workspace(
        self, workspace_id: str, *, per_page: int = 50, token: str | None = None
    ) -> list[BillingInvoice]:
        return await self.list(
            filter=filter_eq("workspace", workspace_id),
            sort="-created",
            per_page=per_page,
            token=token,
        )

    async def get_by_reference(
        self, reference: str, *, token: str | None = None
    ) -> BillingInvoice | None:
        return await self.first(filter=filter_eq("reference", reference), token=token)

    async def get_by_provider_reference(
        self, provider_reference: str, *, token: str | None = None
    ) -> BillingInvoice | None:
        return await self.first(
            filter=filter_eq("provider_reference", provider_reference), token=token
        )

    async def get_by_correlation_token(
        self, correlation_token: str, *, token: str | None = None
    ) -> BillingInvoice | None:
        return await self.first(
            filter=filter_eq("correlation_token", correlation_token), token=token
        )

    async def get_by_provider_subscription_id(
        self, subscription_id: str, *, token: str | None = None
    ) -> BillingInvoice | None:
        return await self.first(
            filter=filter_eq("provider_subscription_id", subscription_id),
            sort="-created",
            token=token,
        )

    async def get_for_job(self, job_id: str, *, token: str | None = None) -> BillingInvoice | None:
        return await self.first(filter=filter_eq("job", job_id), sort="-created", token=token)

    async def list_open(
        self, *, per_page: int = 100, token: str | None = None
    ) -> list[BillingInvoice]:
        return await self.list(
            filter=_in_statuses("status", _OPEN_STATUSES),
            sort="created",
            per_page=per_page,
            token=token,
        )

    async def list_open_for_workspace(
        self, workspace_id: str, *, per_page: int = 20, token: str | None = None
    ) -> list[BillingInvoice]:
        return await self.list(
            filter=(
                f"{filter_eq('workspace', workspace_id)} && "
                f"({_in_statuses('status', _OPEN_STATUSES)})"
            ),
            sort="-created",
            per_page=per_page,
            token=token,
        )

    async def count_open_for_workspace(self, workspace_id: str, *, token: str | None = None) -> int:
        return await self.count(
            filter=(
                f"{filter_eq('workspace', workspace_id)} && "
                f"({_in_statuses('status', _OPEN_STATUSES)})"
            ),
            token=token,
        )


class BillingEventRepository(PocketBaseRepository[BillingEvent]):
    collection = "billing_events"
    model = BillingEvent

    async def get_by_key(self, event_key: str, *, token: str | None = None) -> BillingEvent | None:
        return await self.first(filter=filter_eq("event_key", event_key), token=token)


class BillingFreeClaimRepository(PocketBaseRepository[BillingFreeClaim]):
    collection = "billing_free_claims"
    model = BillingFreeClaim

    async def count_for_workspace(
        self, workspace_id: str, *, kind: str, token: str | None = None
    ) -> int:
        return await self.count(
            filter=f"{filter_eq('workspace', workspace_id)} && {filter_eq('kind', kind)}",
            token=token,
        )

    async def claim(
        self,
        workspace_id: str,
        *,
        kind: str,
        max_slots: int,
        job_id: str | None = None,
        token: str | None = None,
    ) -> BillingFreeClaim | None:
        """Claim the next free slot, bounded by ``max_slots``.

        The database's unique index on ``(workspace, kind, slot)`` is the
        concurrency guard: two racing requests both try slot N, one wins and the
        other moves on (or gives up after the last slot). Counting first only
        avoids pointless writes; it is not the correctness boundary.
        """
        if max_slots <= 0:
            return None
        used = await self.count_for_workspace(workspace_id, kind=kind, token=token)
        for slot in range(used + 1, max_slots + 1):
            try:
                return await self.create(
                    {"workspace": workspace_id, "kind": kind, "slot": slot, "job": job_id},
                    token=token,
                )
            except ConflictError, ValidationError:
                # Slot taken by a concurrent request; try the next one.
                continue
        return None

    async def list_for_workspace(
        self, workspace_id: str, *, token: str | None = None
    ) -> list[BillingFreeClaim]:
        return await self.list(
            filter=filter_eq("workspace", workspace_id),
            sort="slot",
            per_page=50,
            token=token,
        )
