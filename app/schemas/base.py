"""Base record type for all PocketBase-backed domain models.

Field names mirror the PocketBase collection fields so repository mapping is a
direct validation with no hand-written translation layer.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Record(BaseModel):
    """Common PocketBase record fields."""

    model_config = ConfigDict(extra="ignore")

    id: str
    created: datetime | None = None
    updated: datetime | None = None
