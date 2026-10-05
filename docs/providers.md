# Providers

Canonical reference. Provider connectors are data-driven: a `providers` record
declares the protocol type, and a per-workspace `provider_connections` record
supplies endpoint/auth/billing mode. The generic OpenAI-compatible adapter covers
OpenAI, Azure-style gateways, Ollama, vLLM and self-hosted gateways without
vendor SDKs in the core. Full detail in
[`providers-and-billing.md`](providers-and-billing.md);
[ADR 0006](decisions/0006-providers-billing.md).

## Admin responsibilities

Admins create providers, models and capabilities at `/admin/providers`,
`/admin/models`, `/admin/model-capabilities`. Routing is capability- and
cost-aware and contains **no model-specific logic**. Credentials are encrypted,
never rendered, and stored in a superuser-only collection.

SSRF protection and its known limitation are documented in
[`security-audit.md`](security-audit.md).
