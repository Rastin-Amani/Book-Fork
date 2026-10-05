// Translation profiles and typed system settings. Profiles are configuration
// records (with optional workspace ownership); no provider-specific defaults
// exist in Python.

const AUTODATE = [
  { type: "autodate", name: "created", onCreate: true, onUpdate: false },
  { type: "autodate", name: "updated", onCreate: true, onUpdate: true },
]

const PROFILE_READ = "workspace = \"\" || workspace.workspace_members_via_workspace.user ?= @request.auth.id"
const PROFILE_WRITE = "workspace.workspace_members_via_workspace.user ?= @request.auth.id"

migrate((app) => {
  const workspacesId = app.findCollectionByNameOrId("workspaces").id

  const profiles = new Collection({
    type: "base",
    name: "translation_profiles",
    listRule: PROFILE_READ,
    viewRule: PROFILE_READ,
    createRule: PROFILE_WRITE,
    updateRule: PROFILE_WRITE,
    deleteRule: PROFILE_WRITE,
    fields: [
      { type: "text", name: "name", required: true, max: 200 },
      { type: "text", name: "description", max: 2000 },
      { type: "relation", name: "workspace", maxSelect: 1, collectionId: workspacesId, cascadeDelete: true },
      { type: "text", name: "source_language", max: 35 },
      { type: "text", name: "target_language", max: 35 },
      { type: "text", name: "source_locale", max: 35 },
      { type: "text", name: "target_locale", max: 35 },
      { type: "text", name: "style", max: 100 },
      { type: "text", name: "tone", max: 100 },
      { type: "text", name: "domain", max: 100 },
      { type: "select", name: "quality_mode", required: true, maxSelect: 1, values: ["fast", "balanced", "quality", "best"] },
      { type: "relation", name: "prompt_template", maxSelect: 1, collectionId: app.findCollectionByNameOrId("prompt_templates").id },
      { type: "json", name: "glossary_ids", maxSize: 2000000 },
      { type: "json", name: "translation_memory_policy", maxSize: 2000000 },
      { type: "json", name: "segmentation_strategy", maxSize: 2000000 },
      { type: "json", name: "context_strategy", maxSize: 2000000 },
      { type: "json", name: "normalization_pipeline", maxSize: 2000000 },
      { type: "json", name: "validation_profile", maxSize: 2000000 },
      { type: "number", name: "temperature" },
      { type: "number", name: "batch_size" },
      { type: "json", name: "context_window_policy", maxSize: 2000000 },
      { type: "bool", name: "is_system_default" },
      { type: "bool", name: "enabled" },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
    indexes: ["CREATE INDEX idx_translation_profiles_workspace ON translation_profiles (workspace)"],
  })
  app.save(profiles)

  const settings = new Collection({
    type: "base",
    name: "system_settings",
    listRule: "@request.auth.id != ''",
    viewRule: "@request.auth.id != ''",
    createRule: null,
    updateRule: null,
    deleteRule: null,
    fields: [
      { type: "text", name: "key", required: true, max: 200 },
      { type: "json", name: "value", maxSize: 2000000 },
      { type: "select", name: "type", required: true, maxSelect: 1, values: ["string", "int", "float", "bool", "json"] },
      { type: "text", name: "description", max: 1000 },
      { type: "text", name: "category", max: 100 },
      { type: "bool", name: "editable" },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
    indexes: ["CREATE UNIQUE INDEX idx_system_settings_key ON system_settings (key)"],
  })
  app.save(settings)
}, (app) => {
  app.delete(app.findCollectionByNameOrId("system_settings"))
  app.delete(app.findCollectionByNameOrId("translation_profiles"))
})
