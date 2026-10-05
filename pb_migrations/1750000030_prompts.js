// Prompt templates and versions. Prompts are database entities, versioned, and
// every translation job snapshots the exact version it used.

const AUTODATE = [
  { type: "autodate", name: "created", onCreate: true, onUpdate: false },
  { type: "autodate", name: "updated", onCreate: true, onUpdate: true },
]

const TEMPLATE_READ = "workspace = \"\" || workspace.workspace_members_via_workspace.user ?= @request.auth.id"
const TEMPLATE_WRITE = "workspace.workspace_members_via_workspace.user ?= @request.auth.id"

migrate((app) => {
  const usersId = app.findCollectionByNameOrId("users").id

  const templates = new Collection({
    type: "base",
    name: "prompt_templates",
    listRule: TEMPLATE_READ,
    viewRule: TEMPLATE_READ,
    createRule: TEMPLATE_WRITE,
    updateRule: TEMPLATE_WRITE,
    deleteRule: TEMPLATE_WRITE,
    fields: [
      { type: "text", name: "name", required: true, max: 200 },
      { type: "text", name: "slug", required: true, max: 120 },
      { type: "text", name: "description", max: 1000 },
      { type: "relation", name: "workspace", maxSelect: 1, collectionId: app.findCollectionByNameOrId("workspaces").id, cascadeDelete: true },
      { type: "select", name: "purpose", required: true, maxSelect: 1, values: ["translation", "detection", "qa", "glossary", "other"] },
      { type: "bool", name: "enabled" },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
    indexes: ["CREATE UNIQUE INDEX idx_prompt_templates_slug ON prompt_templates (slug)"],
  })
  app.save(templates)

  const versions = new Collection({
    type: "base",
    name: "prompt_versions",
    listRule: "template.workspace = \"\" || template.workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    viewRule: "template.workspace = \"\" || template.workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    createRule: "template.workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    updateRule: "template.workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    deleteRule: "template.workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    fields: [
      { type: "relation", name: "template", required: true, maxSelect: 1, collectionId: templates.id, cascadeDelete: true },
      { type: "number", name: "version", required: true, min: 1 },
      { type: "text", name: "body", required: true },
      { type: "json", name: "variables", maxSize: 2000000 },
      { type: "select", name: "status", required: true, maxSelect: 1, values: ["draft", "active", "archived"] },
      { type: "relation", name: "created_by", maxSelect: 1, collectionId: usersId },
      { type: "text", name: "notes", max: 2000 },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
    indexes: [
      "CREATE UNIQUE INDEX idx_prompt_versions_unique ON prompt_versions (template, version)",
    ],
  })
  app.save(versions)
}, (app) => {
  app.delete(app.findCollectionByNameOrId("prompt_versions"))
  app.delete(app.findCollectionByNameOrId("prompt_templates"))
})
