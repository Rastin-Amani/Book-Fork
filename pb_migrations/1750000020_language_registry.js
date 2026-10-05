// Language registry: generic, data-driven language and locale metadata.
// Direction is DATA here — no RTL/LTR list exists anywhere in Python.

const AUTODATE = [
  { type: "autodate", name: "created", onCreate: true, onUpdate: false },
  { type: "autodate", name: "updated", onCreate: true, onUpdate: true },
]

const PUBLIC_READ = "" // anyone may read reference data
const ADMIN_ONLY = null // only superusers/service may write

migrate((app) => {
  const languages = new Collection({
    type: "base",
    name: "languages",
    listRule: PUBLIC_READ,
    viewRule: PUBLIC_READ,
    createRule: ADMIN_ONLY,
    updateRule: ADMIN_ONLY,
    deleteRule: ADMIN_ONLY,
    fields: [
      { type: "text", name: "language_code", required: true, max: 35 },
      { type: "text", name: "iso_639_1", max: 3 },
      { type: "text", name: "iso_639_3", max: 3 },
      { type: "text", name: "name", required: true, max: 120 },
      { type: "text", name: "native_name", max: 120 },
      { type: "text", name: "bcp47_prefix", max: 35 },
      { type: "text", name: "script_code", max: 8 },
      { type: "select", name: "direction", required: true, maxSelect: 1, values: ["ltr", "rtl"] },
      { type: "text", name: "default_locale", max: 35 },
      { type: "bool", name: "enabled" },
      { type: "bool", name: "popular" },
      { type: "number", name: "sort_order" },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
    indexes: [
      "CREATE UNIQUE INDEX idx_languages_code ON languages (language_code)",
      "CREATE INDEX idx_languages_enabled ON languages (enabled)",
    ],
  })
  app.save(languages)

  const variants = new Collection({
    type: "base",
    name: "language_variants",
    listRule: PUBLIC_READ,
    viewRule: PUBLIC_READ,
    createRule: ADMIN_ONLY,
    updateRule: ADMIN_ONLY,
    deleteRule: ADMIN_ONLY,
    fields: [
      { type: "relation", name: "language", required: true, maxSelect: 1, collectionId: languages.id, cascadeDelete: true },
      { type: "text", name: "locale", required: true, max: 35 },
      { type: "text", name: "script_code", max: 8 },
      { type: "select", name: "direction", maxSelect: 1, values: ["ltr", "rtl"] },
      { type: "text", name: "name", max: 120 },
      { type: "text", name: "native_name", max: 120 },
      // Language-specific behaviour is configuration, never `if language == ...`.
      { type: "json", name: "normalization_pipeline", maxSize: 2000000 },
      { type: "json", name: "segmentation_strategy", maxSize: 2000000 },
      { type: "json", name: "punctuation_profile", maxSize: 2000000 },
      { type: "json", name: "quotation_profile", maxSize: 2000000 },
      { type: "json", name: "formatting_profile", maxSize: 2000000 },
      { type: "bool", name: "enabled" },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
    indexes: [
      "CREATE UNIQUE INDEX idx_language_variants_unique ON language_variants (language, locale)",
    ],
  })
  app.save(variants)
}, (app) => {
  app.delete(app.findCollectionByNameOrId("language_variants"))
  app.delete(app.findCollectionByNameOrId("languages"))
})
