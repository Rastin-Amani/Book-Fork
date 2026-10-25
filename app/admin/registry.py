"""Declarative admin configuration.

Admin behaviour is data: a list of resources, their fields and how to render
them. The generic CRUD routes and templates are driven entirely by this registry,
so adding an editable collection is a data change, not new handler code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

FieldKind = str  # text | textarea | int | float | bool | json | select | relation | readonly


@dataclass(frozen=True, slots=True)
class AdminField:
    name: str
    label: str
    kind: FieldKind = "text"
    required: bool = False
    choices: tuple[str, ...] = ()
    relation: str | None = None  # target resource slug for relation selects
    help: str | None = None


@dataclass(frozen=True, slots=True)
class AdminResource:
    slug: str
    title: str
    repo: str
    label: str
    category: str
    fields: tuple[AdminField, ...]
    list_fields: tuple[str, ...]
    description: str | None = None
    can_create: bool = True
    can_update: bool = True
    can_delete: bool = True
    order: str | None = "-created"
    default_filter: str | None = None
    hidden: bool = False
    actions: tuple[str, ...] = field(default_factory=tuple)


def _f(*args: object, **kwargs: object) -> AdminField:
    return AdminField(*args, **kwargs)  # type: ignore[arg-type]


RESOURCES: tuple[AdminResource, ...] = (
    AdminResource(
        slug="users",
        title="Users",
        repo="users",
        label="email",
        category="access",
        description="Accounts are created through Google/GitHub sign-in; admins can moderate them.",
        can_create=False,
        list_fields=("email", "name", "verified", "created"),
        fields=(
            _f("email", "Email", "readonly"),
            _f("name", "Name"),
            _f("verified", "Verified", "bool"),
        ),
    ),
    AdminResource(
        slug="workspaces",
        title="Workspaces",
        repo="workspaces",
        label="name",
        category="access",
        list_fields=("name", "slug", "owner", "plan", "created"),
        fields=(
            _f("name", "Name", required=True),
            _f("slug", "Slug", required=True),
            _f("owner", "Owner", "relation", relation="users"),
            _f("plan", "Plan"),
        ),
    ),
    AdminResource(
        slug="workspace-members",
        title="Workspace members",
        repo="workspace_members",
        label="user",
        category="access",
        list_fields=("workspace", "user", "role"),
        fields=(
            _f("workspace", "Workspace", "relation", relation="workspaces", required=True),
            _f("user", "User", "relation", relation="users", required=True),
            _f("role", "Role", "select", choices=("owner", "admin", "member", "viewer")),
        ),
    ),
    AdminResource(
        slug="documents",
        title="Documents",
        repo="documents",
        label="original_filename",
        category="content",
        description="Source documents. Upload happens through the app; admins can inspect/remove.",
        can_create=False,
        list_fields=("original_filename", "document_type", "status", "workspace", "created"),
        fields=(
            _f("original_filename", "Original filename", "readonly"),
            _f("display_name", "Display name"),
            _f(
                "status",
                "Status",
                "select",
                choices=("uploaded", "detecting", "ready", "parsing", "parsed", "failed"),
            ),
            _f("source_language", "Source language"),
            _f("document_type", "Type", "readonly"),
            _f("file_size", "Size (bytes)", "readonly"),
        ),
    ),
    AdminResource(
        slug="translation-jobs",
        title="Translation jobs",
        repo="jobs",
        label="id",
        category="content",
        can_create=False,
        list_fields=("document", "status", "target_language", "progress", "workspace", "created"),
        fields=(
            _f(
                "status",
                "Status",
                "select",
                choices=(
                    "queued",
                    "preparing",
                    "parsing",
                    "segmenting",
                    "translating",
                    "finalizing",
                    "completed",
                    "failed",
                    "cancelled",
                    "cancelling",
                ),
            ),
            _f("target_language", "Target language", "readonly"),
            _f(
                "quality_mode",
                "Quality",
                "select",
                choices=("fast", "economy", "balanced", "quality", "best"),
            ),
            _f("error_code", "Error code", "readonly"),
            _f("error_message", "Error message", "readonly"),
        ),
    ),
    AdminResource(
        slug="failed-jobs",
        title="Failed jobs",
        repo="jobs",
        label="id",
        category="content",
        description="Jobs that ended in failure or were cancelled.",
        can_create=False,
        default_filter='status = "failed" || status = "cancelled"',
        list_fields=("document", "status", "error_code", "error_message", "workspace", "created"),
        fields=(
            _f("status", "Status", "select", choices=("queued", "failed", "cancelled")),
            _f("error_code", "Error code", "readonly"),
            _f("error_message", "Error message", "readonly"),
        ),
    ),
    AdminResource(
        slug="job-events",
        title="Job events",
        repo="job_events",
        label="type",
        category="content",
        can_create=False,
        can_update=False,
        list_fields=("job", "type", "level", "message", "created"),
        fields=(
            _f("job", "Job", "readonly"),
            _f("type", "Type", "readonly"),
            _f("level", "Level", "select", choices=("info", "warning", "error")),
            _f("message", "Message", "readonly"),
            _f("data", "Data", "json"),
        ),
    ),
    AdminResource(
        slug="providers",
        title="Providers",
        repo="providers",
        label="name",
        category="providers",
        list_fields=("name", "slug", "provider_type", "enabled"),
        fields=(
            _f("name", "Name", required=True),
            _f("slug", "Slug", required=True),
            _f(
                "provider_type",
                "Type",
                "select",
                choices=("openai_compatible", "anthropic", "gemini", "ollama", "custom"),
            ),
            _f(
                "authentication_type",
                "Auth type",
                "select",
                choices=("api_key", "bearer", "none", "custom"),
            ),
            _f("base_url", "Base URL"),
            _f("enabled", "Enabled", "bool"),
            _f("description", "Description", "textarea"),
        ),
    ),
    AdminResource(
        slug="provider-connections",
        title="Provider connections",
        repo="connections",
        label="name",
        category="providers",
        description="Per-workspace connections. Credentials are never shown here.",
        list_fields=("name", "provider", "workspace", "billing_mode", "enabled"),
        fields=(
            _f("workspace", "Workspace", "relation", relation="workspaces", required=True),
            _f("provider", "Provider", "relation", relation="providers", required=True),
            _f("name", "Name", required=True),
            _f("auth_type", "Auth type", "select", choices=("api_key", "bearer", "none", "custom")),
            _f("billing_mode", "Billing", "select", choices=("managed", "own_api")),
            _f("base_url", "Base URL"),
            _f("enabled", "Enabled", "bool"),
            _f("config", "Config", "json"),
        ),
    ),
    AdminResource(
        slug="models",
        title="Models",
        repo="models",
        label="model_identifier",
        category="providers",
        description="No routing logic is code: capability and pricing live here.",
        list_fields=("model_identifier", "provider", "enabled", "quality_score"),
        fields=(
            _f("provider", "Provider", "relation", relation="providers", required=True),
            _f("model_identifier", "Identifier", required=True),
            _f("display_name", "Display name"),
            _f("enabled", "Enabled", "bool"),
            _f("context_window", "Context window", "int"),
            _f("max_output_tokens", "Max output tokens", "int"),
            _f("supports_structured_output", "Structured output", "bool"),
            _f("supports_vision", "Vision", "bool"),
            _f("supports_temperature", "Temperature", "bool"),
            _f("input_cost_per_million_tokens", "Input $/1M", "float"),
            _f("output_cost_per_million_tokens", "Output $/1M", "float"),
            _f("request_cost", "Request cost", "float"),
            _f("quality_score", "Quality score", "float"),
        ),
    ),
    AdminResource(
        slug="model-capabilities",
        title="Model capabilities",
        repo="capabilities",
        label="model",
        category="providers",
        list_fields=("model", "source_language", "target_language", "supported", "preferred"),
        fields=(
            _f("model", "Model", "relation", relation="models", required=True),
            _f("source_language", "Source language", required=True),
            _f("target_language", "Target language", required=True),
            _f("supported", "Supported", "bool"),
            _f("preferred", "Preferred", "bool"),
            _f("quality_score", "Quality score", "float"),
            _f("notes", "Notes", "textarea"),
        ),
    ),
    AdminResource(
        slug="prompt-templates",
        title="Prompt templates",
        repo="prompt_templates",
        label="name",
        category="prompts",
        list_fields=("name", "slug", "purpose", "enabled"),
        fields=(
            _f("name", "Name", required=True),
            _f("slug", "Slug", required=True),
            _f(
                "purpose",
                "Purpose",
                "select",
                choices=("translation", "detection", "qa", "glossary", "other"),
            ),
            _f("workspace", "Workspace", "relation", relation="workspaces"),
            _f("description", "Description", "textarea"),
            _f("enabled", "Enabled", "bool"),
        ),
        actions=("new-version",),
    ),
    AdminResource(
        slug="prompt-versions",
        title="Prompt versions",
        repo="prompt_versions",
        label="id",
        category="prompts",
        list_fields=("template", "version", "status", "created"),
        fields=(
            _f("template", "Template", "relation", relation="prompt-templates", required=True),
            _f("version", "Version", "int", required=True),
            _f("status", "Status", "select", choices=("draft", "active", "archived")),
            _f("body", "Body", "textarea", required=True),
            _f("notes", "Notes", "textarea"),
        ),
        actions=("activate", "archive", "compare"),
    ),
    AdminResource(
        slug="translation-profiles",
        title="Translation profiles",
        repo="profiles",
        label="name",
        category="prompts",
        list_fields=("name", "quality_mode", "workspace", "is_system_default", "enabled"),
        fields=(
            _f("name", "Name", required=True),
            _f(
                "quality_mode",
                "Quality",
                "select",
                choices=("fast", "economy", "balanced", "quality", "best"),
            ),
            _f("description", "Description", "textarea"),
            _f("workspace", "Workspace", "relation", relation="workspaces"),
            _f("source_language", "Source language"),
            _f("target_language", "Target language"),
            _f("prompt_template", "Prompt template", "relation", relation="prompt-templates"),
            _f("temperature", "Temperature", "float"),
            _f("batch_size", "Batch size", "int"),
            _f("is_system_default", "System default", "bool"),
            _f("enabled", "Enabled", "bool"),
        ),
    ),
    AdminResource(
        slug="languages",
        title="Languages",
        repo="languages",
        label="name",
        category="languages",
        description="Direction, script and locale defaults are data, never code.",
        list_fields=("language_code", "name", "direction", "enabled", "popular"),
        fields=(
            _f("language_code", "Code", required=True),
            _f("name", "Name", required=True),
            _f("native_name", "Native name"),
            _f("direction", "Direction", "select", choices=("ltr", "rtl")),
            _f("script_code", "Script"),
            _f("default_locale", "Default locale"),
            _f("iso_639_1", "ISO 639-1"),
            _f("iso_639_3", "ISO 639-3"),
            _f("enabled", "Enabled", "bool"),
            _f("popular", "Popular", "bool"),
            _f("sort_order", "Sort order", "float"),
            _f("metadata", "Metadata", "json"),
        ),
    ),
    AdminResource(
        slug="language-variants",
        title="Language variants",
        repo="language_variants",
        label="locale",
        category="languages",
        list_fields=("language", "locale", "direction", "enabled"),
        fields=(
            _f("language", "Language", "relation", relation="languages", required=True),
            _f("locale", "Locale", required=True),
            _f("name", "Name"),
            _f("native_name", "Native name"),
            _f("script_code", "Script"),
            _f("direction", "Direction", "select", choices=("ltr", "rtl")),
            _f("normalization_pipeline", "Normalization", "json"),
            _f("segmentation_strategy", "Segmentation", "json"),
            _f("enabled", "Enabled", "bool"),
        ),
    ),
    AdminResource(
        slug="glossaries",
        title="Glossaries",
        repo="glossaries",
        label="name",
        category="knowledge",
        list_fields=("name", "workspace", "enabled"),
        fields=(
            _f("workspace", "Workspace", "relation", relation="workspaces", required=True),
            _f("name", "Name", required=True),
            _f("description", "Description", "textarea"),
            _f("enabled", "Enabled", "bool"),
        ),
    ),
    AdminResource(
        slug="glossary-terms",
        title="Glossary terms",
        repo="glossary_terms",
        label="source_term",
        category="knowledge",
        list_fields=(
            "source_term",
            "target_term",
            "source_language",
            "target_language",
            "glossary",
        ),
        fields=(
            _f("glossary", "Glossary", "relation", relation="glossaries", required=True),
            _f("source_language", "Source language", required=True),
            _f("target_language", "Target language", required=True),
            _f("source_term", "Source term", required=True),
            _f("target_term", "Target term", required=True),
            _f("preferred", "Preferred", "bool"),
            _f("forbidden", "Forbidden", "bool"),
            _f("notes", "Notes", "textarea"),
        ),
    ),
    AdminResource(
        slug="translation-memory",
        title="Translation memory",
        repo="memory",
        label="source_text",
        category="knowledge",
        list_fields=("source_language", "target_language", "source_text", "approved"),
        fields=(
            _f("workspace", "Workspace", "relation", relation="workspaces"),
            _f("source_language", "Source language", required=True),
            _f("target_language", "Target language", required=True),
            _f("source_text", "Source", "textarea", required=True),
            _f("translation", "Translation", "textarea", required=True),
            _f("approved", "Approved", "bool"),
        ),
    ),
    AdminResource(
        slug="system-settings",
        title="System settings",
        repo="settings",
        label="key",
        category="system",
        description="Business defaults. Values are typed.",
        can_create=True,
        can_delete=False,
        list_fields=("key", "value", "type", "category"),
        fields=(
            _f("key", "Key", required=True),
            _f("value", "Value", "json", required=True),
            _f("type", "Type", "select", choices=("string", "int", "float", "bool", "json")),
            _f("description", "Description", "textarea"),
            _f("category", "Category"),
            _f("editable", "Editable", "bool"),
        ),
    ),
    AdminResource(
        slug="workers",
        title="Workers",
        repo="workers",
        label="worker_id",
        category="system",
        can_create=False,
        can_update=False,
        list_fields=("worker_id", "status", "current_jobs", "last_heartbeat"),
        fields=(
            _f("worker_id", "Worker", "readonly"),
            _f("host", "Host", "readonly"),
            _f("status", "Status", "readonly"),
            _f("current_jobs", "Current jobs", "readonly"),
            _f("last_heartbeat", "Last heartbeat", "readonly"),
        ),
    ),
)

RESOURCES_BY_SLUG: dict[str, AdminResource] = {r.slug: r for r in RESOURCES}

CATEGORY_TITLES: dict[str, str] = {
    "access": "Access",
    "content": "Content",
    "providers": "Providers & models",
    "prompts": "Prompts & profiles",
    "languages": "Languages",
    "knowledge": "Glossaries & memory",
    "system": "System",
}


def get_resource(slug: str) -> AdminResource | None:
    return RESOURCES_BY_SLUG.get(slug)
