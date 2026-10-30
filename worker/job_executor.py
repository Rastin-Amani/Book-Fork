"""Job executor: the resumable per-job translation pipeline.

Runs one translation job from claim to completion:

    prepare → reserve → parse → segment → translate → finalize → export → settle → complete

Every stage is idempotent enough to re-run after a crash, and cancellation is
cooperative between safe checkpoints.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
from app.billing.pricing import ProviderPricing, ProviderPricingEngine
from app.documents.adapters.base import (
    DocumentType,
    ExportOptions,
    ParseOptions,
)
from app.documents.model import CanonicalDocument
from app.documents.safety import safe_temp_dir, sha256_bytes
from app.documents.segmentation.base import SegmentationConfig, SegmentationStrategy
from app.documents.service import DocumentEngine
from app.exceptions import (
    BookForkError,
    ConfigurationError,
    NotFoundError,
    UpstreamError,
)
from app.jobs.config import WorkerSettings
from app.jobs.retry import RetryService
from app.jobs.store import JobStore
from app.logging import get_logger
from app.observability.metrics import metrics
from app.providers.base import (
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
    TranslationProvider,
)
from app.providers.errors import ProviderError, ProviderErrorCategory
from app.repositories.documents import DocumentRepository
from app.schemas.documents import Document
from app.schemas.translation import TranslationJob, TranslationSegment
from app.storage.base import Storage
from app.translation.engine import (
    TranslationEngine,
    TranslationOutcome,
    TranslationSegmentInput,
)
from app.translation.glossary import GlossaryRetriever
from app.translation.memory import TranslationMemoryStore
from app.translation.plan import TranslationPlan
from app.translation.policy_engine import TranslationPolicyEngine

logger = get_logger(__name__)

_COMPLETED_SEGMENT_STATUSES = {"validated", "translated"}
# Bounded so a genuinely broken dependency still surfaces as a failed job
# instead of requeueing forever.
_MAX_UPSTREAM_REQUEUES = 20
_RETRYABLE_CATEGORIES = {
    "rate_limited",
    "timeout",
    "provider_unavailable",
    "unknown_provider_error",
    "invalid_response",
    "empty_translation",
    # A dropped placeholder is often nondeterministic; give the model another go.
    "validation_failed",
}
_CHARS_PER_TOKEN = 4


def _apply_statuses(statuses: dict[str, str], outcome: TranslationOutcome) -> None:
    """Fold a batch outcome's segment statuses into the live progress map."""
    for result in outcome.results:
        statuses[result.segment_id] = "validated" if result.status == "completed" else "failed"


ProviderFactory = Callable[[TranslationJob, TranslationPlan], Awaitable[TranslationProvider]]
MemoryFactory = Callable[[TranslationJob], TranslationMemoryStore | None]
GlossaryFactory = Callable[[TranslationJob], GlossaryRetriever | None]


class JobCancelledError(Exception):
    """Raised when a job's cooperative cancellation is observed."""


class _LimitedProvider:
    """Wraps a provider with a global provider-concurrency semaphore."""

    def __init__(self, provider: TranslationProvider, semaphore: asyncio.Semaphore) -> None:
        self._provider = provider
        self._semaphore = semaphore
        self.name = provider.name
        self.supports_structured_output = provider.supports_structured_output

    async def translate(self, request: ProviderRequest) -> ProviderResponse:
        async with self._semaphore:
            return await self._provider.translate(request)

    async def estimate_usage(self, request: ProviderRequest) -> Any:
        return await self._provider.estimate_usage(request)

    async def validate_connection(self) -> bool:
        return await self._provider.validate_connection()

    async def aclose(self) -> None:
        closer = getattr(self._provider, "aclose", None)
        if closer is not None:
            await closer()


class JobExecutor:
    def __init__(
        self,
        *,
        store: JobStore,
        documents: DocumentEngine,
        policy: TranslationPolicyEngine,
        engine: TranslationEngine,
        storage: Storage,
        document_repository: DocumentRepository,
        provider_factory: ProviderFactory,
        settings: WorkerSettings,
        retry: RetryService | None = None,
        memory_factory: MemoryFactory | None = None,
        glossary_factory: GlossaryFactory | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        now: Callable[[], datetime] | None = None,
        temp_root: Path | None = None,
        output_formats: Sequence[DocumentType] | None = None,
        page_size: str = "a5",
        font_dir: str | None = None,
        render_backend: str = "pymupdf",
    ) -> None:
        self._store = store
        self._documents = documents
        self._policy = policy
        self._engine = engine
        self._storage = storage
        self._document_repo = document_repository
        self._provider_factory = provider_factory
        self._settings = settings
        self._retry = retry or RetryService()
        self._memory_factory = memory_factory
        self._glossary_factory = glossary_factory
        self._sleep = sleep or asyncio.sleep
        self._now = now or (lambda: datetime.now(UTC))
        self._temp_root = temp_root
        self._output_formats = (
            tuple(output_formats) if output_formats else (DocumentType.EPUB, DocumentType.PDF)
        )
        self._page_size = page_size
        self._font_dir = font_dir
        self._render_backend = render_backend
        self._provider_semaphore = asyncio.Semaphore(settings.max_provider_concurrency)
        self._attempt_counts: dict[str, int] = {}

    async def execute(self, job: TranslationJob) -> None:
        self._attempt_counts = {}
        lease_id = job.lease_id or ""
        try:
            if lease_id:
                from worker.heartbeat import LeaseHeartbeat

                async with LeaseHeartbeat(
                    store=self._store,
                    job_id=job.id,
                    lease_id=lease_id,
                    lease_seconds=self._settings.lease_seconds,
                    interval_seconds=float(self._settings.heartbeat_seconds),
                ):
                    await self._pipeline(job)
            else:
                await self._pipeline(job)
        except JobCancelledError:
            await self._cancel(job)
        except UpstreamError as exc:
            # PocketBase (or storage) being briefly unreachable is not a job
            # failure: the job is resumable, so put it back in the queue and
            # let the next poll continue where this run stopped.
            await self._requeue_upstream(job, exc)
        except BookForkError as exc:
            await self._fail(job, error_code=exc.code, message=exc.message)
        except Exception as exc:
            logger.exception("job_unhandled_error", job_id=job.id, error=type(exc).__name__)
            await self._fail(
                job,
                error_code="internal_error",
                message=f"Unexpected worker error ({type(exc).__name__}); see worker logs.",
            )

    # -- pipeline ------------------------------------------------------------
    async def _pipeline(self, job: TranslationJob) -> None:
        plan = self._load_plan(job)
        await self._event(job.id, "preparing", "Job claimed")
        await self._check_cancel(job)

        document = await self._document_repo.get(job.document)
        segments = await self._ensure_segments(job, plan, document)

        await self._check_cancel(job)
        await self._store.update_job(job.id, {"status": "translating"})
        await self._event(job.id, "translating", "Translation started")

        memory = self._memory_factory(job) if self._memory_factory else None
        glossary = self._glossary_factory(job) if self._glossary_factory else None
        provider = _LimitedProvider(
            await self._provider_factory(job, plan), self._provider_semaphore
        )

        try:
            usage = await self._translate_all(job, plan, segments, provider, memory, glossary)
        finally:
            await provider.aclose()
        if usage is not None:
            metrics.inc("book_fork_tokens_total", usage.input_tokens, direction="input")
            metrics.inc("book_fork_tokens_total", usage.output_tokens, direction="output")
        segments = await self._store.list_segments(job.id)
        progress = self._progress(segments)
        await self._store.update_job(job.id, {"progress": progress["percentage"]})
        await self._check_cancel(job)

        failed = [s for s in segments if s.status == "failed"]
        if failed:
            await self._store.update_job(
                job.id,
                {
                    "status": "failed",
                    "failed_segments": progress["failed"],
                    "completed_segments": progress["completed"],
                    "total_segments": progress["total"],
                    "actual_provider_cost": self._provider_cost(plan, usage),
                    "error_code": "segments_failed",
                    "error_message": f"{len(failed)} segment(s) failed; retry failed segments.",
                },
            )
            await self._event(
                job.id, "failed", "Translation finished with failed segments", level="error"
            )
            metrics.inc("book_fork_jobs_failed_total")
            return

        await self._store.update_job(
            job.id,
            {
                "status": "finalizing",
                "completed_segments": progress["completed"],
                "total_segments": progress["total"],
            },
        )
        await self._finalize_output(job, document, plan)
        await self._store.update_job(
            job.id,
            {
                "status": "completed",
                "progress": 100.0,
                "completed_segments": progress["completed"],
                "total_segments": progress["total"],
                "actual_provider_cost": self._provider_cost(plan, usage),
                "completed_at": self._now().isoformat(),
            },
        )
        await self._event(job.id, "completed", "Job completed")
        metrics.inc("book_fork_jobs_completed_total")

    # -- stages --------------------------------------------------------------
    def _load_plan(self, job: TranslationJob) -> TranslationPlan:
        if not job.snapshot:
            raise ConfigurationError("Job has no translation plan snapshot.")
        return TranslationPlan.from_snapshot(job.snapshot)

    async def _ensure_segments(
        self, job: TranslationJob, plan: TranslationPlan, document: Document
    ) -> list[TranslationSegment]:
        segments = await self._store.list_segments(job.id)
        if segments:
            return segments  # resume: already parsed and segmented

        await self._store.update_job(job.id, {"status": "parsing"})
        await self._event(job.id, "parsing", "Retrieving and parsing source")
        if not document.storage_key:
            raise ConfigurationError("Document has no source stored.")
        document_type = _document_type(document)
        async with self._documents.materialize(self._storage, document.storage_key) as source:
            parse_result = await self._documents.parse_file(
                source,
                document_type=document_type,
                options=ParseOptions(document_id=job.document),
            )
        await self._documents.store_assets(self._storage, parse_result, document_id=job.document)
        await self._documents.store_canonical(
            self._storage, parse_result.document, document_id=job.document
        )

        await self._store.update_job(job.id, {"status": "segmenting"})
        await self._event(job.id, "segmenting", "Segmenting document")
        config = SegmentationConfig(
            strategy=SegmentationStrategy(
                plan.segmentation_strategy
                if plan.segmentation_strategy in SegmentationStrategy._value2member_map_
                else "structure_aware"
            ),
            source_language=plan.source.tag,
            target_language=plan.target.tag,
            max_chars=int(
                (plan.profile_snapshot.get("segmentation_strategy") or {}).get("max_chars", 1200)
            ),
        )
        segments_found = self._documents.segment(parse_result.document, config)
        records = [
            {
                "job": job.id,
                "document": job.document,
                "sequence_index": index,
                "source_block_type": segment.block_type.value,
                "source_text": segment.text,
                "status": "pending",
                "attempt_count": 0,
                "metadata": {
                    "segment_key": segment.id,
                    "block_id": segment.block_id,
                    "section_id": segment.section_id,
                },
            }
            # PocketBase rejects 0 on a required number field ("Cannot be
            # blank"), so segment ordering starts at 1.
            for index, segment in enumerate(segments_found, start=1)
        ]
        created = await self._store.create_segments(job.id, records)
        await self._store.update_job(job.id, {"total_segments": len(created)})
        return created

    async def _translate_all(
        self,
        job: TranslationJob,
        plan: TranslationPlan,
        segments: Sequence[TranslationSegment],
        provider: TranslationProvider,
        memory: TranslationMemoryStore | None,
        glossary: GlossaryRetriever | None,
    ) -> ProviderUsage | None:
        # A retry resumes whatever is not finished: completed segments are
        # skipped, while both previously failed and never-attempted (pending)
        # segments are translated. Filtering to status == "failed" here used to
        # strand pending segments after an infrastructure failure — the retry
        # then completed the job with most of the book untranslated.
        pending = [
            segment
            for segment in segments
            if segment.source_text and not self._is_completed(segment)
        ]
        total_usage = None
        remaining = list(pending)
        attempt = 0
        active_plan = plan
        # Live status per segment so job progress advances batch by batch.
        statuses: dict[str, str] = {segment.id: segment.status.value for segment in segments}
        total = len(segments)
        while remaining and attempt < max(1, self._settings.retry.max_attempts):
            attempt += 1
            inputs = [
                TranslationSegmentInput(
                    id=segment.id,
                    text=segment.source_text or "",
                    metadata=segment.metadata or {},
                )
                for segment in remaining
            ]
            by_id = {segment.id: segment for segment in remaining}
            recorded: set[str] = set()

            async def record_batch(
                batch: Sequence[TranslationSegmentInput],
                batch_outcome: TranslationOutcome,
                _by_id: dict[str, TranslationSegment] = by_id,
                _plan: TranslationPlan = active_plan,
                _recorded: set[str] = recorded,
                _statuses: dict[str, str] = statuses,
            ) -> None:
                # Persist each batch as it lands so progress is visible and a
                # crash mid-document does not lose already-translated segments.
                # A rejected credential is systemic: stop at the first batch
                # instead of writing thousands of doomed attempts.
                if any(
                    result.status == "failed"
                    and result.error_category == ProviderErrorCategory.AUTHENTICATION.value
                    for result in batch_outcome.results
                ):
                    raise ProviderError(
                        ProviderErrorCategory.AUTHENTICATION,
                        "The provider rejected the API key. "
                        "Update the connection credential and retry.",
                    )
                batch_segments = [s for item in batch if (s := _by_id.get(item.id))]
                await self._record_outcome(job, _plan, batch_segments, batch_outcome)
                _recorded.update(item.id for item in batch)
                _apply_statuses(_statuses, batch_outcome)
                await self._persist_progress(job.id, _statuses, total)

            outcome = await self._engine.translate(
                active_plan,
                inputs,
                provider=provider,
                memory=memory,
                glossary=glossary,
                persist_memory=bool((job.metadata or {}).get("persist_memory", False)),
                on_batch=record_batch,
            )
            total_usage = (
                outcome.usage if total_usage is None else total_usage.merged(outcome.usage)
            )
            # Batch results were recorded by the callback; only memory hits
            # (and anything else outside a batch) still need recording.
            leftover = [result for result in outcome.results if result.segment_id not in recorded]
            if leftover:
                await self._record_outcome(
                    job,
                    active_plan,
                    remaining,
                    replace(outcome, results=leftover),
                )
                _apply_statuses(statuses, replace(outcome, results=leftover))
                await self._persist_progress(job.id, statuses, total)

            retryable = [
                segment
                for segment in remaining
                if self._last_result(outcome, segment.id) is not None
                and self._last_result(outcome, segment.id).status == "failed"
                and self._last_result(outcome, segment.id).error_category in _RETRYABLE_CATEGORIES
            ]
            context_too_large = [
                segment
                for segment in remaining
                if self._last_result(outcome, segment.id) is not None
                and self._last_result(outcome, segment.id).error_category == "context_too_large"
            ]
            if context_too_large and self._settings.context_repair_enabled:
                active_plan = self._repair_plan(active_plan)
                remaining = context_too_large
                await self._event(job.id, "context_repair", "Reducing context and retrying")
                continue
            if retryable:
                await self._retry.wait(self._settings.retry, attempt=attempt)
                remaining = retryable
                continue
            break
        return total_usage

    async def _record_outcome(
        self,
        job: TranslationJob,
        plan: TranslationPlan,
        segments: Sequence[TranslationSegment],
        outcome: TranslationOutcome,
    ) -> None:
        by_id = {segment.id: segment for segment in segments}
        for result in outcome.results:
            segment = by_id.get(result.segment_id)
            if segment is None:
                continue
            attempt_number = self._attempt_counts.get(segment.id, 0) + 1
            self._attempt_counts[segment.id] = attempt_number
            completed = result.status == "completed"
            now_iso = self._now().isoformat()
            await self._store.create_attempt(
                {
                    "segment": segment.id,
                    "job": job.id,
                    "attempt_number": attempt_number,
                    "provider": plan.provider_id,
                    "provider_connection": plan.provider_connection_id,
                    "model": plan.model_id,
                    "prompt_template": plan.prompt_template_id,
                    "prompt_version": plan.prompt_version_id,
                    "request_completed_at": now_iso,
                    "status": "succeeded" if completed else "failed",
                    "validation_status": "passed" if completed else "failed",
                    "error_code": result.error_category,
                    "error_message": result.error_message,
                    "input_tokens": 0,
                    "output_tokens": 0,
                }
            )
            await self._store.update_segment(
                segment.id,
                {
                    "status": "validated" if completed else "failed",
                    "translated_text": result.translation,
                    "attempt_count": attempt_number,
                    "last_attempt_at": now_iso,
                },
            )
            if completed:
                metrics.inc("book_fork_segments_processed_total")
            else:
                metrics.inc("book_fork_segment_failures_total")

    async def _persist_progress(self, job_id: str, statuses: dict[str, str], total: int) -> None:
        """Write live segment counts and percentage onto the job row."""
        completed = sum(1 for status in statuses.values() if status in _COMPLETED_SEGMENT_STATUSES)
        failed = sum(1 for status in statuses.values() if status == "failed")
        percent = (completed / total * 100.0) if total else 0.0
        await self._store.update_job(
            job_id,
            {
                "completed_segments": completed,
                "failed_segments": failed,
                "total_segments": total,
                "progress": round(percent, 2),
            },
        )

    def _repair_plan(self, plan: TranslationPlan) -> TranslationPlan:
        new_batch = max(self._settings.context_repair_min_batch_size, max(1, plan.batch_size // 2))
        reduced_context = replace(
            plan.context_policy,
            max_previous_segments=0,
            max_context_tokens=max(256, plan.context_policy.max_context_tokens // 2),
        )
        return replace(plan, batch_size=new_batch, context_policy=reduced_context)

    async def _finalize_output(
        self, job: TranslationJob, document: Document, plan: TranslationPlan
    ) -> None:
        canonical = await self._canonical_for(job, document)
        _apply_translations(canonical, await self._store.list_segments(job.id))
        assets = await self._load_assets(canonical)
        resolver = (lambda asset: assets.get(asset.id)) if assets else None

        outputs: dict[str, dict[str, Any]] = {}
        with safe_temp_dir(base=self._temp_root) as tmp:
            for format_type in self._output_formats:
                artifact = await self._export_format(
                    canonical, format_type, plan, tmp, resolver, job.id
                )
                if artifact is None:
                    continue
                data = await anyio.to_thread.run_sync(artifact.path.read_bytes)
                extension = artifact.extension.lstrip(".") or "bin"
                key = f"documents/{job.document}/outputs/{job.id}.{extension}"
                await self._storage.put(key, data, content_type=artifact.media_type)
                outputs[format_type.value] = {
                    "key": key,
                    "mime": artifact.media_type,
                    "extension": artifact.extension,
                    "checksum": sha256_bytes(data),
                    "size": len(data),
                }

        primary = _primary_output(outputs)
        metadata = dict(job.metadata or {})
        metadata["outputs"] = outputs
        await self._store.update_job(
            job.id,
            {
                "output_storage_key": primary.get("key"),
                "output_checksum": primary.get("checksum"),
                "output_mime_type": primary.get("mime"),
                "metadata": metadata,
            },
        )

    async def _canonical_for(self, job: TranslationJob, document: Document) -> CanonicalDocument:
        """Load the parsed canonical, rebuilding it if storage lost it.

        A document parsed before persistent storage was mounted keeps its
        segments in PocketBase but loses canonical.json on the next deploy.
        Re-parsing the source restores it without re-translating anything.
        """
        key = f"documents/{job.document}/canonical/v1.json"
        try:
            return await self._documents.load_canonical(self._storage, key)
        except FileNotFoundError, NotFoundError:
            if not document.storage_key:
                raise ConfigurationError("Document has no source stored.") from None
            logger.warning("canonical_missing_rebuilding", job_id=job.id, key=key)
            async with self._documents.materialize(self._storage, document.storage_key) as source:
                result = await self._documents.parse_file(
                    source,
                    document_type=_document_type(document),
                    options=ParseOptions(document_id=job.document),
                )
            await self._documents.store_assets(self._storage, result, document_id=job.document)
            await self._documents.store_canonical(
                self._storage, result.document, document_id=job.document
            )
            await self._event(job.id, "rebuilt", "Rebuilt the parsed document from its source")
            return result.document

    async def _export_format(
        self,
        canonical: CanonicalDocument,
        format_type: DocumentType,
        plan: TranslationPlan,
        tmp: Path,
        resolver: Any,
        job_id: str,
    ) -> Any:
        try:
            return await self._documents.export_file(
                canonical,
                document_type=format_type,
                options=ExportOptions(
                    target_language=plan.target.tag,
                    target_direction=plan.target.direction,
                    target_script=plan.target.script,
                    document_title=None,
                    page_size=self._page_size,
                    render_backend=self._render_backend,
                    output_dir=tmp,
                    asset_resolver=resolver,
                    font_dir=self._font_dir,
                ),
            )
        except ConfigurationError as exc:
            logger.warning(
                "export_format_unavailable",
                job_id=job_id,
                format=format_type.value,
                error=exc.message,
            )
            return None
        except BookForkError as exc:
            logger.warning(
                "export_format_failed", job_id=job_id, format=format_type.value, error=exc.code
            )
            return None

    async def _load_assets(self, canonical: CanonicalDocument) -> dict[str, bytes]:
        assets: dict[str, bytes] = {}
        for asset in canonical.assets:
            if not asset.storage_key or not asset.media_type.startswith("image/"):
                continue
            try:
                assets[asset.id] = await self._storage.read(asset.storage_key)
            except Exception as exc:
                logger.warning("asset_unavailable", asset_id=asset.id, error=type(exc).__name__)
        return assets

    # -- cost ----------------------------------------------------------------
    def _provider_pricing(self, plan: TranslationPlan) -> ProviderPricing:
        data = plan.pricing or {}
        return ProviderPricing(
            input_cost_per_million_tokens=float(data.get("input_cost_per_million_tokens") or 0.0),
            output_cost_per_million_tokens=float(data.get("output_cost_per_million_tokens") or 0.0),
            request_cost=float(data.get("request_cost") or 0.0),
        )

    def _provider_cost(self, plan: TranslationPlan, usage: ProviderUsage | None) -> float:
        if usage is None:
            return 0.0
        return ProviderPricingEngine().compute(
            self._provider_pricing(plan),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )

    # -- helpers -------------------------------------------------------------
    def _is_completed(self, segment: TranslationSegment) -> bool:
        return segment.status in _COMPLETED_SEGMENT_STATUSES and bool(segment.translated_text)

    @staticmethod
    def _last_result(outcome: TranslationOutcome, segment_id: str) -> Any:
        for result in outcome.results:
            if result.segment_id == segment_id:
                return result
        return None

    def _progress(self, segments: Sequence[TranslationSegment]) -> dict[str, Any]:
        total = len(segments)
        completed = sum(1 for segment in segments if self._is_completed(segment))
        failed = sum(1 for segment in segments if segment.status == "failed")
        pending = total - completed - failed
        percentage = (completed / total * 100.0) if total else 0.0
        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "pending": pending,
            "percentage": round(percentage, 2),
        }

    async def _check_cancel(self, job: TranslationJob) -> None:
        current = await self._store.get_job(job.id)
        if current.cancellation_requested:
            raise JobCancelledError()

    async def _cancel(self, job: TranslationJob) -> None:
        await self._store.update_job(job.id, {"status": "cancelling"})
        await self._store.update_job(
            job.id, {"status": "cancelled", "cancelled_at": self._now().isoformat()}
        )
        await self._event(job.id, "cancelled", "Job cancelled by request")
        metrics.inc("book_fork_jobs_cancelled_total")

    async def _requeue_upstream(self, job: TranslationJob, exc: UpstreamError) -> None:
        """Put a job back in the queue when an upstream dependency blips."""
        metadata = dict(job.metadata or {})
        attempts = int(metadata.get("upstream_retries", 0)) + 1
        if attempts > _MAX_UPSTREAM_REQUEUES:
            await self._fail(job, error_code=exc.code, message=exc.message)
            return
        metadata["upstream_retries"] = attempts
        await self._store.update_job(
            job.id,
            {
                "status": "queued",
                "worker_id": "",
                "lease_id": "",
                "lease_expires_at": None,
                "error_code": "",
                "error_message": "",
                "metadata": metadata,
            },
        )
        logger.warning(
            "job_requeued_upstream",
            job_id=job.id,
            attempts=attempts,
            error=type(exc).__name__,
        )
        with contextlib.suppress(Exception):
            await self._event(
                job.id,
                "requeued",
                f"Upstream unavailable; requeued (attempt {attempts}).",
                level="warning",
            )

    async def _fail(self, job: TranslationJob, *, error_code: str, message: str) -> None:
        await self._store.update_job(
            job.id,
            {"status": "failed", "error_code": error_code, "error_message": message},
        )
        await self._event(job.id, "failed", message, level="error")
        metrics.inc("book_fork_jobs_failed_total")

    async def _event(self, job_id: str, type: str, message: str, *, level: str = "info") -> None:
        logger.info("job_event", job_id=job_id, type=type, status=type)
        metrics.inc("book_fork_job_events_total", type=type)
        await self._store.append_event(job_id, type=type, message=message, level=level)


def _document_type(document: Document) -> DocumentType:
    raw = (document.document_type or "").lower()
    try:
        return DocumentType(raw)
    except ValueError as exc:
        raise ConfigurationError(f"Unsupported document type {raw!r}.") from exc


_PRIMARY_FORMAT_ORDER = ("epub", "pdf")


def _primary_output(outputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    for name in _PRIMARY_FORMAT_ORDER:
        if name in outputs:
            return outputs[name]
    return next(iter(outputs.values()), {})


def _apply_translations(
    document: CanonicalDocument, segments: Sequence[TranslationSegment]
) -> None:
    by_block: dict[str, str] = {}
    for segment in segments:
        if segment.translated_text and segment.metadata:
            block_id = str(segment.metadata.get("block_id") or "")
            if block_id:
                by_block[block_id] = segment.translated_text
    for block in document.iter_blocks():
        if block.id in by_block:
            block.translated_text = by_block[block.id]
