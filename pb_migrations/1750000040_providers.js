// Providers, connections, models, capabilities. Providers are RECORDS; the code
// only contains protocol adapters. Credentials live in a separate collection
// that is never readable through the public API (superuser/service only).

const AUTODATE = [
  { type: "autodate", name: "created", onCreate: true, onUpdate: false },
  { type: "autodate", name: "updated", onCreate: true, onUpdate: true },
]

const PUBLIC_READ = ""
const ADMIN_ONLY = null

migrate((app) => {
  const workspacesId = app.findCollectionByNameOrId("workspaces").id

  const providers = new Collection({
    type: "base",
    name: "providers",
    listRule: PUBLIC_READ,
    viewRule: PUBLIC_READ,
    createRule: ADMIN_ONLY,
    updateRule: ADMIN_ONLY,
    deleteRule: ADMIN_ONLY,
    fields: [
      { type: "text", name: "name", required: true, max: 120 },
      { type: "text", name: "slug", required: true, max: 80 },
      { type: "select", name: "provider_type", required: true, maxSelect: 1, values: ["openai_compatible", "anthropic", "gemini", "ollama", "custom"] },
      { type: "text", name: "base_url", max: 500 },
      { type: "bool", name: "enabled" },
      { type: "text", name: "description", max: 2000 },
      { type: "select", name: "authentication_type", required: true, maxSelect: 1, values: ["api_key", "bearer", "none", "custom"] },
      { type: "json", name: "capabilities", maxSize: 2000000 },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
    indexes: ["CREATE UNIQUE INDEX idx_providers_slug ON providers (slug)"],
  })
  app.save(providers)

  const connections = new Collection({
    type: "base",
    name: "provider_connections",
    listRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    viewRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    createRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    updateRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    deleteRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    fields: [
      { type: "relation", name: "workspace", required: true, maxSelect: 1, collectionId: workspacesId, cascadeDelete: true },
      { type: "relation", name: "provider", required: true, maxSelect: 1, collectionId: providers.id, cascadeDelete: true },
      { type: "text", name: "name", required: true, max: 200 },
      { type: "text", name: "base_url", max: 500 },
      { type: "select", name: "auth_type", required: true, maxSelect: 1, values: ["api_key", "bearer", "none", "custom"] },
      { type: "bool", name: "enabled" },
      { type: "json", name: "config", maxSize: 2000000 },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
  })
  app.save(connections)

  // Secret material. No API rule exposes this collection to end users; only
  // trusted server-side operations using the service credential may read it.
  const credentials = new Collection({
    type: "base",
    name: "provider_credentials",
    listRule: ADMIN_ONLY,
    viewRule: ADMIN_ONLY,
    createRule: ADMIN_ONLY,
    updateRule: ADMIN_ONLY,
    deleteRule: ADMIN_ONLY,
    fields: [
      { type: "relation", name: "connection", required: true, maxSelect: 1, collectionId: connections.id, cascadeDelete: true },
      { type: "text", name: "encrypted_credential", required: true },
      { type: "text", name: "key_hint", max: 40 },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
    indexes: ["CREATE UNIQUE INDEX idx_provider_credentials_connection ON provider_credentials (connection)"],
  })
  app.save(credentials)

  const models = new Collection({
    type: "base",
    name: "provider_models",
    listRule: PUBLIC_READ,
    viewRule: PUBLIC_READ,
    createRule: ADMIN_ONLY,
    updateRule: ADMIN_ONLY,
    deleteRule: ADMIN_ONLY,
    fields: [
      { type: "relation", name: "provider", required: true, maxSelect: 1, collectionId: providers.id, cascadeDelete: true },
      { type: "text", name: "model_identifier", required: true, max: 200 },
      { type: "text", name: "display_name", max: 200 },
      { type: "bool", name: "enabled" },
      { type: "number", name: "context_window" },
      { type: "number", name: "max_output_tokens" },
      { type: "bool", name: "supports_structured_output" },
      { type: "bool", name: "supports_vision" },
      { type: "bool", name: "supports_temperature" },
      { type: "number", name: "input_cost_per_million_tokens" },
      { type: "number", name: "output_cost_per_million_tokens" },
      { type: "number", name: "quality_score" },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
    indexes: [
      "CREATE UNIQUE INDEX idx_provider_models_unique ON provider_models (provider, model_identifier)",
    ],
  })
  app.save(models)

  const capabilities = new Collection({
    type: "base",
    name: "model_capabilities",
    listRule: PUBLIC_READ,
    viewRule: PUBLIC_READ,
    createRule: ADMIN_ONLY,
    updateRule: ADMIN_ONLY,
    deleteRule: ADMIN_ONLY,
    fields: [
      { type: "relation", name: "model", required: true, maxSelect: 1, collectionId: models.id, cascadeDelete: true },
      { type: "text", name: "source_language", required: true, max: 35 },
      { type: "text", name: "target_language", required: true, max: 35 },
      { type: "bool", name: "supported" },
      { type: "bool", name: "preferred" },
      { type: "number", name: "quality_score" },
      { type: "text", name: "notes", max: 2000 },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
    indexes: [
      "CREATE UNIQUE INDEX idx_model_capabilities_unique ON model_capabilities (model, source_language, target_language)",
    ],
  })
  app.save(capabilities)
}, (app) => {
  app.delete(app.findCollectionByNameOrId("model_capabilities"))
  app.delete(app.findCollectionByNameOrId("provider_models"))
  app.delete(app.findCollectionByNameOrId("provider_credentials"))
  app.delete(app.findCollectionByNameOrId("provider_connections"))
  app.delete(app.findCollectionByNameOrId("providers"))
})
