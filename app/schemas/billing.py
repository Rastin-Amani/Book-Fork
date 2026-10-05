"""Credit ledger domain records."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from app.schemas.base import Record


class TransactionType(StrEnum):
    PURCHASE = "purchase"
    BONUS = "bonus"
    RESERVATION = "reservation"
    CONSUMPTION = "consumption"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"
    EXPIRATION = "expiration"


class UsageEventType(StrEnum):
    TRANSLATION = "translation"
    DETECTION = "detection"
    VALIDATION = "validation"
    EXPORT = "export"
    OTHER = "other"


class CreditWallet(Record):
    workspace: str
    balance: float
    currency: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreditTransaction(Record):
    wallet: str
    type: TransactionType
    amount: float
    balance_before: float
    balance_after: float
    reason: str | None = None
    job: str | None = None
    reference: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UsageEvent(Record):
    workspace: str
    event_type: UsageEventType
    job: str | None = None
    provider: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    provider_cost: float | None = None
    credits: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
