"""Seed reproducibility, and the guarantee that seeds carry no secrets."""

from __future__ import annotations

from app.repositories.languages import LanguageRepository, LanguageVariantRepository
from app.repositories.prompts import PromptTemplateRepository, PromptVersionRepository
from app.repositories.providers import ProviderRepository
from app.repositories.settings import SystemSettingRepository
from app.repositories.translation import TranslationProfileRepository
from app.services.seed import SEEDS_DIR, SeedService, load_seed


def _service(pb) -> SeedService:
    return SeedService(
        languages=LanguageRepository(pb),
        variants=LanguageVariantRepository(pb),
        settings=SystemSettingRepository(pb),
        providers=ProviderRepository(pb),
        profiles=TranslationProfileRepository(pb),
        templates=PromptTemplateRepository(pb),
        versions=PromptVersionRepository(pb),
    )


def _sizes(fake_pb) -> dict[str, int]:
    return {name: len(records) for name, records in fake_pb.collections.items()}


async def test_seed_is_reproducible(pb, fake_pb) -> None:
    service = _service(pb)
    await service.run()
    first = _sizes(fake_pb)
    await service.run()
    second = _sizes(fake_pb)
    assert first == second  # re-running creates no duplicates


async def test_seed_creates_expected_records(pb, fake_pb) -> None:
    await _service(pb).run()
    assert len(fake_pb.collections["languages"]) == len(load_seed("languages")["languages"])
    assert len(fake_pb.collections["language_variants"]) == len(load_seed("languages")["variants"])
    assert len(fake_pb.collections["providers"]) == len(load_seed("providers")["providers"])
    assert len(fake_pb.collections["translation_profiles"]) == 3
    assert len(fake_pb.collections["prompt_templates"]) == 2
    assert len(fake_pb.collections["system_settings"]) == len(
        load_seed("system_settings")["settings"]
    )


async def test_seeded_language_metadata_is_derived(pb, fake_pb) -> None:
    await _service(pb).run()
    languages = {r["language_code"]: r for r in fake_pb.collections["languages"].values()}
    assert languages["fa"]["direction"] == "rtl"
    assert languages["fa"]["script_code"] == "Arab"
    assert languages["fa"]["name"] == "Persian"
    assert languages["de"]["direction"] == "ltr"
    assert languages["zh"]["direction"] == "ltr"


async def test_seeded_prompt_is_versioned(pb, fake_pb) -> None:
    await _service(pb).run()
    versions = fake_pb.collections["prompt_versions"].values()
    active = [v for v in versions if v["status"] == "active"]
    assert active
    assert all(v["version"] >= 1 for v in active)


def test_seed_files_contain_no_secrets() -> None:
    forbidden = ["password", "secret", "sk-", '"api_key":', "BEGIN PRIVATE KEY"]
    for path in sorted(SEEDS_DIR.glob("*.json")):
        text = path.read_text(encoding="utf-8").lower()
        for needle in forbidden:
            assert needle.lower() not in text, f"{path.name} must not contain {needle!r}"
