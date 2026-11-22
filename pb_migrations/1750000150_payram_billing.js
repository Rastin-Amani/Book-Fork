// Billing base schema: invoices, notification deliveries and the free-book allowance.
//
// Originally added with the PayRam adapter; the provider value `payram` is kept
// so any historical rows remain readable after the Gumroad migration
// (1750000200_gumroad_billing.js).
//
// One managed translation job is one book order. The job is created in
// `awaiting_payment` and only queued once a verified payment (or a
// configured free allowance) grants the entitlement.
//
// Rules on these collections are deliberately asymmetric: customers may read
// their own workspace's records, but every write goes through the PocketBase
// service credential from the server. A browser can never create an invoice or
// mark one paid.

const AUTODATE = [
  { type: "autodate", name: "created", onCreate: true, onUpdate: false },
  { type: "autodate", name: "updated", onCreate: true, onUpdate: true },
]

migrate((app) => {
  // A managed job must exist before payment, so the status enum needs a
  // pre-queue state. The worker only claims `queued`.
  const jobs = app.findCollectionByNameOrId("translation_jobs")
  const statusField = jobs.fields.getByName("status")
  if (!statusField.values.includes("awaiting_payment")) {
    statusField.values.push("awaiting_payment")
    app.save(jobs)
  }

  const workspacesId = app.findCollectionByNameOrId("workspaces").id
  const usersId = app.findCollectionByNameOrId("users").id
  const jobsId = jobs.id

  const invoices = new Collection({
    type: "base",
    name: "billing_invoices",
    listRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    viewRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    createRule: null,
    updateRule: null,
    deleteRule: null,
    fields: [
      { type: "relation", name: "workspace", required: true, maxSelect: 1, collectionId: workspacesId, cascadeDelete: true },
      { type: "relation", name: "created_by", maxSelect: 1, collectionId: usersId },
      { type: "relation", name: "job", maxSelect: 1, collectionId: jobsId },
      { type: "text", name: "reference", required: true, max: 40 },
      { type: "select", name: "product_type", required: true, maxSelect: 1, values: ["managed_book"] },
      { type: "text", name: "product_name", required: true, max: 200 },
      { type: "number", name: "amount", required: true },
      { type: "text", name: "currency", required: true, max: 10 },
      { type: "select", name: "status", required: true, maxSelect: 1, values: ["pending", "awaiting_payment", "partially_paid", "paid", "cancelled", "failed", "refunded", "review"] },
      { type: "select", name: "provider", maxSelect: 1, values: ["payram", "free", "none"] },
      // The provider reference is unique only when set: unset is stored as ''
      // and a plain unique index would reject the second unpaid invoice.
      { type: "text", name: "provider_reference", max: 200 },
      { type: "url", name: "checkout_url" },
      { type: "number", name: "paid_amount" },
      { type: "text", name: "paid_currency", max: 10 },
      { type: "date", name: "expires_at" },
      { type: "date", name: "paid_at" },
      { type: "date", name: "fulfilled_at" },
      { type: "text", name: "failure_reason", max: 1000 },
      { type: "json", name: "product_snapshot", maxSize: 2000000 },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
    indexes: [
      "CREATE UNIQUE INDEX idx_billing_invoices_reference ON billing_invoices (reference)",
      "CREATE UNIQUE INDEX idx_billing_invoices_provider_reference ON billing_invoices (provider_reference) WHERE provider_reference != ''",
      "CREATE INDEX idx_billing_invoices_workspace ON billing_invoices (workspace, created)",
      "CREATE INDEX idx_billing_invoices_status ON billing_invoices (status, created)",
      "CREATE INDEX idx_billing_invoices_job ON billing_invoices (job)",
    ],
  })
  app.save(invoices)

  const events = new Collection({
    type: "base",
    name: "billing_events",
    // Webhook deliveries are operational records, not customer data.
    listRule: null,
    viewRule: null,
    createRule: null,
    updateRule: null,
    deleteRule: null,
    fields: [
      { type: "text", name: "provider", required: true, max: 50 },
      // Stable provider event key; the unique index makes redelivery a no-op.
      { type: "text", name: "event_key", required: true, max: 250 },
      { type: "relation", name: "invoice", maxSelect: 1, collectionId: invoices.id },
      { type: "select", name: "event_type", maxSelect: 1, values: ["payment", "cancellation"] },
      { type: "text", name: "provider_reference", max: 200 },
      { type: "text", name: "status", max: 50 },
      { type: "json", name: "payload", maxSize: 2000000 },
      { type: "bool", name: "processed" },
      { type: "date", name: "processed_at" },
      { type: "text", name: "error", max: 200 },
      ...AUTODATE,
    ],
    indexes: [
      "CREATE UNIQUE INDEX idx_billing_events_key ON billing_events (event_key)",
      "CREATE INDEX idx_billing_events_invoice ON billing_events (invoice, created)",
      "CREATE INDEX idx_billing_events_processed ON billing_events (processed, created)",
    ],
  })
  app.save(events)

  const claims = new Collection({
    type: "base",
    name: "billing_free_claims",
    listRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    viewRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    createRule: null,
    updateRule: null,
    deleteRule: null,
    fields: [
      { type: "relation", name: "workspace", required: true, maxSelect: 1, collectionId: workspacesId, cascadeDelete: true },
      { type: "text", name: "kind", required: true, max: 50 },
      { type: "number", name: "slot", required: true },
      { type: "relation", name: "invoice", maxSelect: 1, collectionId: invoices.id },
      { type: "relation", name: "job", maxSelect: 1, collectionId: jobsId },
      ...AUTODATE,
    ],
    indexes: [
      // The correctness boundary for bounded free books: two racing requests
      // cannot both take the same slot.
      "CREATE UNIQUE INDEX idx_billing_free_claims_slot ON billing_free_claims (workspace, kind, slot)",
      "CREATE INDEX idx_billing_free_claims_workspace ON billing_free_claims (workspace, created)",
    ],
  })
  app.save(claims)
}, (app) => {
  app.delete(app.findCollectionByNameOrId("billing_free_claims"))
  app.delete(app.findCollectionByNameOrId("billing_events"))
  app.delete(app.findCollectionByNameOrId("billing_invoices"))
  // The extra `awaiting_payment` status value is intentionally left in place:
  // removing a select value while records still reference it would corrupt
  // existing jobs, and a superset is backwards compatible.
})
