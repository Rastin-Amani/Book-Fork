"""Translation job creation and pre-flight estimation.

The web layer calls this service; it never assembles plans or pricing inline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.billing.estimation import JobEstimate, estimate_from_characters
from app.billing.pricing import BookPricing, ProviderPricing
from app.exceptions import ConfigurationError
from app.repositories.documents import DocumentRepository
from app.repositories.translation import TranslationJobRepository
from app.schemas.documents import Document
from app.schemas.translation import TranslationJob
from app.settings.service import SettingsService
from app.translation.plan import TranslationPlan
from app.translation.policy_engine import PlanRequest, TranslationPolicyEngine

_KEY_BOOK_PRICE = "billing.book_price_usd"
_KEY_PAGES_PER_BLOCK = "billing.pages_per_block"
_KEY_WORDS_PER_PAGE = "billing.words_per_page"
_KEY_CURRENCY = "billing.default_currency"


@dataclass(frozen=True, slots=True)
class TranslationEstimate:
    plan: TranslationPlan
    estimate: JobEstimate
    billing_mode: str
    pages: int
    blocks: int
    price: float
    currency: str
    provider_cost: float
    model_identifier: str | None
    provider_connection_id: str | None


class TranslationJobService:
    def __init__(
        self,
        *,
        jobs: TranslationJobRepository,
        documents: DocumentRepository,
        policy: TranslationPolicyEngine,
        settings: SettingsService | None = None,
        token: str | None = None,
    ) -> None:
        self._jobs = jobs
        self._documents = documents
        self._policy = policy
        self._settings = settings
        self._token = token

    async def build_plan(
        self,
        *,
        workspace_id: str,
        source_language: str,
        target_language: str,
        source_locale: str | None = None,
        target_locale: str | None = None,
        profile_id: str | None = None,
        connection_id: str | None = None,
        quality_mode: str | None = None,
    ) -> TranslationPlan:
        return await self._policy.build_plan(
            PlanRequest(
                source_language=source_language,
                target_language=target_language,
                workspace_id=workspace_id,
                source_locale=source_locale,
                target_locale=target_locale,
                profile_id=profile_id,
                provider_connection_id=connection_id,
                quality_mode=quality_mode,
            ),
            segments=[],
        )

    async def estimate(self, *, document: Document, plan: TranslationPlan) -> TranslationEstimate:
        pricing_data = plan.pricing or {}
        provider_pricing = ProviderPricing(
            input_cost_per_million_tokens=float(
                pricing_data.get("input_cost_per_million_tokens") or 0.0
            ),
            output_cost_per_million_tokens=float(
                pricing_data.get("output_cost_per_million_tokens") or 0.0
            ),
            request_cost=float(pricing_data.get("request_cost") or 0.0),
        )
        book_pricing = BookPricing(
            billing_mode=plan.billing_mode,
            price_per_book=float(await self._setting(_KEY_BOOK_PRICE, 7.0)),
            pages_per_block=int(await self._setting(_KEY_PAGES_PER_BLOCK, 1000)),
            words_per_page=int(await self._setting(_KEY_WORDS_PER_PAGE, 300)),
            currency=str(await self._setting(_KEY_CURRENCY, "USD")),
        )
        estimate = estimate_from_characters(
            int(document.file_size or 0),
            provider_pricing=provider_pricing,
            book_pricing=book_pricing,
        )
        return TranslationEstimate(
            plan=plan,
            estimate=estimate,
            billing_mode=plan.billing_mode,
            pages=estimate.pages,
            blocks=estimate.blocks,
            price=estimate.price,
            currency=estimate.currency,
            provider_cost=estimate.provider_cost,
            model_identifier=plan.model_identifier,
            provider_connection_id=plan.provider_connection_id,
        )

    async def create(
        self,
        *,
        workspace_id: str,
        created_by: str,
        document: Document,
        plan: TranslationPlan,
        persist_memory: bool = False,
    ) -> TranslationJob:
        if plan.provider_connection_id is None and plan.model_id is None:
            raise ConfigurationError(
                "No provider/model is configured for this language pair. Add a provider first."
            )
        estimate = await self.estimate(document=document, plan=plan)
        order = {
            "billing_mode": estimate.billing_mode,
            "pages": estimate.pages,
            "blocks": estimate.blocks,
            "amount": estimate.price,
            "currency": estimate.currency,
        }
        return await self._jobs.create(
            {
                "workspace": workspace_id,
                "document": document.id,
                "source_language": plan.source.tag,
                "source_locale": plan.source.locale,
                "target_language": plan.target.tag,
                "target_locale": plan.target.locale,
                "profile": plan.profile_id,
                "provider_connection": plan.provider_connection_id,
                "model": plan.model_id,
                "prompt_version": plan.prompt_version_id,
                "quality_mode": plan.quality_mode,
                "status": "queued",
                "progress": 0.0,
                "total_segments": 0,
                "completed_segments": 0,
                "failed_segments": 0,
                "estimated_provider_cost": estimate.provider_cost,
                "snapshot": plan.snapshot(),
                "created_by": created_by,
                "metadata": {"persist_memory": persist_memory, "order": order},
            },
            token=self._token,
        )

    async def _setting(self, key: str, default: Any) -> Any:
        if self._settings is None:
            return default
        return await self._settings.get(key, default)
