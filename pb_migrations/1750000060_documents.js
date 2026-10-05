// Documents and their structural sections. Source language is optional: a
// document may be uploaded before auto-detection, and detection is overridable.

const AUTODATE = [
  { type: "autodate", name: "created", onCreate: true, onUpdate: false },
  { type: "autodate", name: "updated", onCreate: true, onUpdate: true },
]

const DOC_ACCESS = "workspace.workspace_members_via_workspace.user ?= @request.auth.id"

migrate((app) => {
  const workspacesId = app.findCollectionByNameOrId("workspaces").id
  const usersId = app.findCollectionByNameOrId("users").id

  const documents = new Collection({
    type: "base",
    name: "documents",
    listRule: DOC_ACCESS,
    viewRule: DOC_ACCESS,
    createRule: DOC_ACCESS,
    updateRule: DOC_ACCESS,
    deleteRule: DOC_ACCESS,
    fields: [
      { type: "relation", name: "workspace", required: true, maxSelect: 1, collectionId: workspacesId, cascadeDelete: true },
      { type: "text", name: "original_filename", required: true, max: 500 },
      { type: "text", name: "display_name", max: 500 },
      { type: "text", name: "mime_type", max: 200 },
      { type: "text", name: "extension", max: 20 },
      { type: "select", name: "document_type", maxSelect: 1, values: ["epub", "pdf", "txt", "docx", "other"] },
      { type: "number", name: "file_size" },
      { type: "text", name: "checksum", max: 128 },
      { type: "text", name: "storage_key", max: 1000 },
      { type: "select", name: "status", required: true, maxSelect: 1, values: ["uploaded", "detecting", "ready", "parsing", "parsed", "failed"] },
      // Optional: unknown until detection runs; user selection overrides.
      { type: "text", name: "source_language", max: 35 },
      { type: "text", name: "source_locale", max: 35 },
      { type: "text", name: "source_script", max: 8 },
      { type: "select", name: "source_direction", maxSelect: 1, values: ["ltr", "rtl"] },
      { type: "text", name: "detected_language", max: 35 },
      { type: "number", name: "detected_confidence" },
      { type: "json", name: "language_detection", maxSize: 2000000 },
      { type: "relation", name: "created_by", required: true, maxSelect: 1, collectionId: usersId },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
    indexes: [
      "CREATE INDEX idx_documents_workspace ON documents (workspace)",
      "CREATE INDEX idx_documents_status ON documents (status)",
    ],
  })
  app.save(documents)

  const sections = new Collection({
    type: "base",
    name: "document_sections",
    listRule: "document.workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    viewRule: "document.workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    createRule: "document.workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    updateRule: "document.workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    deleteRule: "document.workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    fields: [
      { type: "relation", name: "document", required: true, maxSelect: 1, collectionId: documents.id, cascadeDelete: true },
      { type: "number", name: "sequence_index", required: true },
      { type: "text", name: "title", max: 500 },
      { type: "select", name: "section_type", maxSelect: 1, values: ["chapter", "part", "section", "front_matter", "back_matter", "other"] },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
    indexes: ["CREATE INDEX idx_document_sections_document ON document_sections (document, sequence_index)"],
  })
  app.save(sections)

  // Self-referential parent link (added after the collection exists).
  sections.fields.add(new RelationField({ name: "parent", maxSelect: 1, collectionId: sections.id }))
  app.save(sections)
}, (app) => {
  app.delete(app.findCollectionByNameOrId("document_sections"))
  app.delete(app.findCollectionByNameOrId("documents"))
})
