"""Idempotent data seeding.

Seeds are DATA (JSON files under ``seeds/``), not hardcoded business logic, and
contain no credentials. Re-running converges: existing records are updated,
missing ones created, and no duplicates are produced.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.language.normalize import normalize_tag
from app.repositories.languages import LanguageRepository, LanguageVariantRepository
from app.repositories.prompts import PromptTemplateRepository, PromptVersionRepository
from app.repositories.providers import ProviderRepository
from app.repositories.settings import SystemSettingRepository
from app.repositories.translation import TranslationProfileRepository
from app.schemas.prompts import PromptStatus

SEEDS_DIR = Path(__file__).resolve().parents[2] / "seeds"


def load_seed(name: str) -> dict[str, Any]:
    """Load a seed JSON file by base name."""
    path = SEEDS_DIR / f"{name}.json"
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Seed file {name}.json must contain an object.")
    return data


@dataclass(slots=True)
class SeedReport:
    created: dict[str, int] = field(default_factory=dict)
    updated: dict[str, int] = field(default_factory=dict)

    def count(self, kind: str, *, created: bool) -> None:
        bucket = self.created if created else self.updated
        bucket[kind] = bucket.get(kind, 0) + 1

    def summary(self) -> str:
        return f"created={self.created} updated={self.updated}"


class SeedService:
    """Applies all seed files through the repository layer."""

    def __init__(
        self,
        *,
        languages: LanguageRepository,
        variants: LanguageVariantRepository,
        settings: SystemSettingRepository,
        providers: ProviderRepository,
        profiles: TranslationProfileRepository,
        templates: PromptTemplateRepository,
        versions: PromptVersionRepository,
        token: str | None = None,
    ) -> None:
        self._languages = languages
        self._variants = variants
        self._settings = settings
        self._providers = providers
        self._profiles = profiles
        self._templates = templates
        self._versions = versions
        self._token = token

    async def run(self) -> SeedReport:
        report = SeedReport()
        await self._seed_languages(report)
        await self._seed_settings(report)
        await self._seed_providers(report)
        await self._seed_profiles(report)
        await self._seed_prompts(report)
        return report

    async def _seed_languages(self, report: SeedReport) -> None:
        data = load_seed("languages")
        id_by_code: dict[str, str] = {}
        for entry in data["languages"]:
            code = entry["language_code"]
            normalized = normalize_tag(code)
            payload = {
                "language_code": code,
                "iso_639_1": normalized.iso_639_1,
                "iso_639_3": normalized.iso_639_3,
                "name": normalized.name,
                "native_name": normalized.native_name,
                "bcp47_prefix": normalized.language,
                "script_code": normalized.script,
                "direction": normalized.direction.value,
                "default_locale": normalized.default_locale,
                "enabled": entry.get("enabled", True),
                "popular": entry.get("popular", False),
                "sort_order": entry.get("sort_order", 0),
            }
            existing = await self._languages.get_by_code(code, token=self._token)
            if existing is None:
                record = await self._languages.create(payload, token=self._token)
                report.count("languages", created=True)
            else:
                record = await self._languages.update(existing.id, payload, token=self._token)
                report.count("languages", created=False)
            id_by_code[code] = record.id

        defaults = data.get("variant_defaults", {})
        for entry in data.get("variants", []):
            language_id = id_by_code.get(entry["language_code"])
            if language_id is None:
                continue
            existing_variant = await self._variants.get_for_language(
                language_id, entry["locale"], token=self._token
            )
            normalized = normalize_tag(entry["locale"])
            payload = {
                "language": language_id,
                "locale": entry["locale"],
                "script_code": normalized.script,
                "direction": normalized.direction.value,
                "name": normalized.name,
                "native_name": normalized.native_name,
                "enabled": entry.get("enabled", True),
                **defaults,
            }
            if existing_variant is None:
                await self._variants.create(payload, token=self._token)
                report.count("language_variants", created=True)
            else:
                await self._variants.update(existing_variant.id, payload, token=self._token)
                report.count("language_variants", created=False)

    async def _seed_settings(self, report: SeedReport) -> None:
        for entry in load_seed("system_settings")["settings"]:
            payload = {
                "key": entry["key"],
                "value": entry["value"],
                "type": entry["type"],
                "description": entry.get("description"),
                "category": entry.get("category"),
                "editable": entry.get("editable", True),
            }
            existing = await self._settings.get_by_key(entry["key"], token=self._token)
            if existing is None:
                await self._settings.create(payload, token=self._token)
                report.count("system_settings", created=True)
            else:
                await self._settings.update(existing.id, payload, token=self._token)
                report.count("system_settings", created=False)

    async def _seed_providers(self, report: SeedReport) -> None:
        for entry in load_seed("providers")["providers"]:
            payload = {k: v for k, v in entry.items()}
            existing = await self._providers.get_by_slug(entry["slug"], token=self._token)
            if existing is None:
                await self._providers.create(payload, token=self._token)
                report.count("providers", created=True)
            else:
                await self._providers.update(existing.id, payload, token=self._token)
                report.count("providers", created=False)

    async def _seed_profiles(self, report: SeedReport) -> None:
        for entry in load_seed("translation_profiles")["profiles"]:
            payload = {k: v for k, v in entry.items()}
            existing = await self._profiles.get_by_name(entry["name"], token=self._token)
            if existing is None:
                await self._profiles.create(payload, token=self._token)
                report.count("translation_profiles", created=True)
            else:
                await self._profiles.update(existing.id, payload, token=self._token)
                report.count("translation_profiles", created=False)

    async def _seed_prompts(self, report: SeedReport) -> None:
        for entry in load_seed("prompt_templates")["templates"]:
            version = entry["version"]
            template_payload = {
                "name": entry["name"],
                "slug": entry["slug"],
                "purpose": entry["purpose"],
                "description": entry.get("description"),
                "enabled": entry.get("enabled", True),
            }
            template = await self._templates.get_by_slug(entry["slug"], token=self._token)
            if template is None:
                template = await self._templates.create(template_payload, token=self._token)
                report.count("prompt_templates", created=True)
            else:
                template = await self._templates.update(
                    template.id, template_payload, token=self._token
                )
                report.count("prompt_templates", created=False)

            active = await self._versions.get_active(template.id, token=self._token)
            if active is None:
                await self._versions.create(
                    {
                        "template": template.id,
                        "version": version["version"],
                        "body": version["body"],
                        "status": version["status"],
                        "variables": version.get("variables", {}),
                    },
                    token=self._token,
                )
                report.count("prompt_versions", created=True)
            elif active.body != version["body"]:
                next_version = await self._versions.next_version_number(
                    template.id, token=self._token
                )
                await self._versions.update(
                    active.id, {"status": PromptStatus.ARCHIVED.value}, token=self._token
                )
                await self._versions.create(
                    {
                        "template": template.id,
                        "version": next_version,
                        "body": version["body"],
                        "status": PromptStatus.ACTIVE.value,
                        "variables": version.get("variables", {}),
                    },
                    token=self._token,
                )
                report.count("prompt_versions", created=True)
