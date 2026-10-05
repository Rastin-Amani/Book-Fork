// Glossaries, glossary terms, and translation memory. Terms and TM entries are
// always language-pair aware: the same source can map differently per target.

const AUTODATE = [
  { type: "autodate", name: "created", onCreate: true, onUpdate: false },
  { type: "autodate", name: "updated", onCreate: true, onUpdate: true },
]

migrate((app) => {
  const workspacesId = app.findCollectionByNameOrId("workspaces").id

  const glossaries = new Collection({
    type: "base",
    name: "glossaries",
    listRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    viewRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    createRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    updateRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    deleteRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    fields: [
      { type: "relation", name: "workspace", required: true, maxSelect: 1, collectionId: workspacesId, cascadeDelete: true },
      { type: "text", name: "name", required: true, max: 200 },
      { type: "text", name: "description", max: 2000 },
      { type: "bool", name: "enabled" },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
  })
  app.save(glossaries)

  const terms = new Collection({
    type: "base",
    name: "glossary_terms",
    listRule: "glossary.workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    viewRule: "glossary.workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    createRule: "glossary.workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    updateRule: "glossary.workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    deleteRule: "glossary.workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    fields: [
      { type: "relation", name: "glossary", required: true, maxSelect: 1, collectionId: glossaries.id, cascadeDelete: true },
      { type: "text", name: "source_language", required: true, max: 35 },
      { type: "text", name: "target_language", required: true, max: 35 },
      { type: "text", name: "source_term", required: true, max: 500 },
      { type: "text", name: "target_term", required: true, max: 500 },
      { type: "bool", name: "case_sensitive" },
      { type: "bool", name: "exact_match" },
      { type: "bool", name: "preferred" },
      { type: "bool", name: "forbidden" },
      { type: "text", name: "notes", max: 2000 },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
    indexes: [
      "CREATE INDEX idx_glossary_terms_pair ON glossary_terms (source_language, target_language)",
      "CREATE INDEX idx_glossary_terms_glossary ON glossary_terms (glossary)",
    ],
  })
  app.save(terms)

  const memory = new Collection({
    type: "base",
    name: "translation_memory_entries",
    listRule: "workspace = \"\" || workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    viewRule: "workspace = \"\" || workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    createRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    updateRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    deleteRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    fields: [
      { type: "relation", name: "workspace", maxSelect: 1, collectionId: workspacesId, cascadeDelete: true },
      { type: "text", name: "source_language", required: true, max: 35 },
      { type: "text", name: "source_locale", max: 35 },
      { type: "text", name: "target_language", required: true, max: 35 },
      { type: "text", name: "target_locale", max: 35 },
      { type: "text", name: "source_text", required: true },
      { type: "text", name: "normalized_source_text", required: true },
      { type: "text", name: "translation", required: true },
      { type: "text", name: "domain", max: 100 },
      { type: "number", name: "quality" },
      { type: "bool", name: "approved" },
      // Hash is language-pair scoped; never used without pair context.
      { type: "text", name: "source_hash", max: 128 },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
    indexes: [
      "CREATE INDEX idx_tm_lookup ON translation_memory_entries (source_language, target_language, normalized_source_text)",
      "CREATE INDEX idx_tm_workspace ON translation_memory_entries (workspace)",
    ],
  })
  app.save(memory)
}, (app) => {
  app.delete(app.findCollectionByNameOrId("translation_memory_entries"))
  app.delete(app.findCollectionByNameOrId("glossary_terms"))
  app.delete(app.findCollectionByNameOrId("glossaries"))
})
