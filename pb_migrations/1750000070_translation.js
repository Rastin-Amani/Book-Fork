// Translation jobs, segments, attempts, and job events. Segment IDs stay stable
// across retries; attempts are append-only per segment. Jobs snapshot the
// resolved configuration so a later config edit cannot change an existing job.

const AUTODATE = [
  { type: "autodate", name: "created", onCreate: true, onUpdate: false },
  { type: "autodate", name: "updated", onCreate: true, onUpdate: true },
]

const JOB_ACCESS = "workspace.workspace_members_via_workspace.user ?= @request.auth.id"
const VIA_JOB = "job.workspace.workspace_members_via_workspace.user ?= @request.auth.id"

migrate((app) => {
  const workspacesId = app.findCollectionByNameOrId("workspaces").id
  const usersId = app.findCollectionByNameOrId("users").id
  const documentsId = app.findCollectionByNameOrId("documents").id
  const sectionsId = app.findCollectionByNameOrId("document_sections").id
  const profilesId = app.findCollectionByNameOrId("translation_profiles").id
  const connectionsId = app.findCollectionByNameOrId("provider_connections").id
  const modelsId = app.findCollectionByNameOrId("provider_models").id
  const providersId = app.findCollectionByNameOrId("providers").id
  const promptTemplatesId = app.findCollectionByNameOrId("prompt_templates").id
  const promptVersionsId = app.findCollectionByNameOrId("prompt_versions").id

  const jobs = new Collection({
    type: "base",
    name: "translation_jobs",
    listRule: JOB_ACCESS,
    viewRule: JOB_ACCESS,
    createRule: JOB_ACCESS,
    updateRule: JOB_ACCESS,
    deleteRule: JOB_ACCESS,
    fields: [
      { type: "relation", name: "workspace", required: true, maxSelect: 1, collectionId: workspacesId, cascadeDelete: true },
      { type: "relation", name: "document", required: true, maxSelect: 1, collectionId: documentsId, cascadeDelete: true },
      { type: "text", name: "source_language", max: 35 },
      { type: "text", name: "source_locale", max: 35 },
      { type: "text", name: "target_language", required: true, max: 35 },
      { type: "text", name: "target_locale", max: 35 },
      { type: "relation", name: "profile", maxSelect: 1, collectionId: profilesId },
      { type: "relation", name: "provider_connection", maxSelect: 1, collectionId: connectionsId },
      { type: "relation", name: "model", maxSelect: 1, collectionId: modelsId },
      { type: "relation", name: "prompt_version", maxSelect: 1, collectionId: promptVersionsId },
      { type: "select", name: "quality_mode", maxSelect: 1, values: ["fast", "balanced", "quality", "best"] },
      { type: "select", name: "status", required: true, maxSelect: 1, values: ["queued", "preparing", "parsing", "segmenting", "translating", "finalizing", "completed", "failed", "cancelled", "cancelling"] },
      { type: "number", name: "progress" },
      { type: "number", name: "total_segments" },
      { type: "number", name: "completed_segments" },
      { type: "number", name: "failed_segments" },
      { type: "number", name: "reserved_credits" },
      { type: "number", name: "actual_credits" },
      { type: "json", name: "snapshot", maxSize: 5000000 },
      { type: "date", name: "started_at" },
      { type: "date", name: "completed_at" },
      { type: "date", name: "cancelled_at" },
      { type: "text", name: "worker_id", max: 200 },
      { type: "text", name: "lease_id", max: 200 },
      { type: "date", name: "lease_expires_at" },
      { type: "date", name: "last_heartbeat" },
      { type: "text", name: "error_code", max: 100 },
      { type: "text", name: "error_message", max: 5000 },
      { type: "relation", name: "created_by", maxSelect: 1, collectionId: usersId },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
    indexes: [
      "CREATE INDEX idx_translation_jobs_workspace ON translation_jobs (workspace, status)",
      "CREATE INDEX idx_translation_jobs_document ON translation_jobs (document)",
      "CREATE INDEX idx_translation_jobs_lease ON translation_jobs (status, lease_expires_at)",
    ],
  })
  app.save(jobs)

  const segments = new Collection({
    type: "base",
    name: "translation_segments",
    listRule: VIA_JOB,
    viewRule: VIA_JOB,
    createRule: VIA_JOB,
    updateRule: VIA_JOB,
    deleteRule: VIA_JOB,
    fields: [
      { type: "relation", name: "job", required: true, maxSelect: 1, collectionId: jobs.id, cascadeDelete: true },
      { type: "relation", name: "document", required: true, maxSelect: 1, collectionId: documentsId, cascadeDelete: true },
      { type: "relation", name: "section", maxSelect: 1, collectionId: sectionsId },
      { type: "number", name: "sequence_index", required: true },
      { type: "number", name: "paragraph_index" },
      { type: "select", name: "source_block_type", maxSelect: 1, values: ["paragraph", "heading", "list_item", "table_cell", "quote", "code", "caption", "other"] },
      { type: "text", name: "source_text" },
      { type: "text", name: "translated_text" },
      { type: "select", name: "status", required: true, maxSelect: 1, values: ["pending", "translating", "translated", "validating", "validated", "failed", "skipped"] },
      { type: "number", name: "attempt_count" },
      { type: "date", name: "last_attempt_at" },
      { type: "number", name: "input_tokens" },
      { type: "number", name: "output_tokens" },
      { type: "number", name: "provider_cost" },
      { type: "number", name: "credits_used" },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
    indexes: [
      "CREATE INDEX idx_translation_segments_job ON translation_segments (job, sequence_index)",
      "CREATE INDEX idx_translation_segments_status ON translation_segments (job, status)",
    ],
  })
  app.save(segments)

  const attempts = new Collection({
    type: "base",
    name: "translation_attempts",
    listRule: VIA_JOB,
    viewRule: VIA_JOB,
    createRule: VIA_JOB,
    updateRule: VIA_JOB,
    deleteRule: VIA_JOB,
    fields: [
      { type: "relation", name: "segment", required: true, maxSelect: 1, collectionId: segments.id, cascadeDelete: true },
      { type: "relation", name: "job", required: true, maxSelect: 1, collectionId: jobs.id, cascadeDelete: true },
      { type: "number", name: "attempt_number", required: true, min: 1 },
      { type: "relation", name: "provider", maxSelect: 1, collectionId: providersId },
      { type: "relation", name: "provider_connection", maxSelect: 1, collectionId: connectionsId },
      { type: "relation", name: "model", maxSelect: 1, collectionId: modelsId },
      { type: "relation", name: "prompt_template", maxSelect: 1, collectionId: promptTemplatesId },
      { type: "relation", name: "prompt_version", maxSelect: 1, collectionId: promptVersionsId },
      { type: "date", name: "request_started_at" },
      { type: "date", name: "request_completed_at" },
      { type: "number", name: "latency_ms" },
      { type: "number", name: "input_tokens" },
      { type: "number", name: "output_tokens" },
      { type: "number", name: "provider_cost" },
      { type: "select", name: "status", required: true, maxSelect: 1, values: ["pending", "succeeded", "failed", "timeout", "cancelled"] },
      { type: "select", name: "validation_status", maxSelect: 1, values: ["pending", "passed", "failed", "skipped"] },
      { type: "text", name: "error_code", max: 100 },
      { type: "text", name: "error_message", max: 5000 },
      // Raw-response retention is configurable; default stores only metadata.
      { type: "json", name: "response_metadata", maxSize: 5000000 },
      ...AUTODATE,
    ],
    indexes: [
      "CREATE INDEX idx_translation_attempts_segment ON translation_attempts (segment, attempt_number)",
      "CREATE INDEX idx_translation_attempts_job ON translation_attempts (job)",
    ],
  })
  app.save(attempts)

  const events = new Collection({
    type: "base",
    name: "job_events",
    listRule: VIA_JOB,
    viewRule: VIA_JOB,
    createRule: VIA_JOB,
    updateRule: VIA_JOB,
    deleteRule: VIA_JOB,
    fields: [
      { type: "relation", name: "job", required: true, maxSelect: 1, collectionId: jobs.id, cascadeDelete: true },
      { type: "text", name: "type", required: true, max: 100 },
      { type: "text", name: "message", max: 5000 },
      { type: "select", name: "level", maxSelect: 1, values: ["info", "warning", "error"] },
      { type: "json", name: "data", maxSize: 2000000 },
      { type: "relation", name: "created_by", maxSelect: 1, collectionId: usersId },
      ...AUTODATE,
    ],
    indexes: ["CREATE INDEX idx_job_events_job ON job_events (job, created)"],
  })
  app.save(events)
}, (app) => {
  app.delete(app.findCollectionByNameOrId("job_events"))
  app.delete(app.findCollectionByNameOrId("translation_attempts"))
  app.delete(app.findCollectionByNameOrId("translation_segments"))
  app.delete(app.findCollectionByNameOrId("translation_jobs"))
})
