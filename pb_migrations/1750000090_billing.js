// Credit ledger. The wallet balance is a cached running total; the ledger
// (credit_transactions) is the auditable source of truth.

const AUTODATE = [
  { type: "autodate", name: "created", onCreate: true, onUpdate: false },
  { type: "autodate", name: "updated", onCreate: true, onUpdate: true },
]

migrate((app) => {
  const workspacesId = app.findCollectionByNameOrId("workspaces").id
  const usersId = app.findCollectionByNameOrId("users").id
  const jobsId = app.findCollectionByNameOrId("translation_jobs").id
  const providersId = app.findCollectionByNameOrId("providers").id
  const modelsId = app.findCollectionByNameOrId("provider_models").id

  const wallets = new Collection({
    type: "base",
    name: "credit_wallets",
    listRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    viewRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    createRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    updateRule: null,
    deleteRule: null,
    fields: [
      { type: "relation", name: "workspace", required: true, maxSelect: 1, collectionId: workspacesId, cascadeDelete: true },
      { type: "number", name: "balance", required: true },
      { type: "text", name: "currency", required: true, max: 10 },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
    indexes: ["CREATE UNIQUE INDEX idx_credit_wallets_unique ON credit_wallets (workspace, currency)"],
  })
  app.save(wallets)

  const transactions = new Collection({
    type: "base",
    name: "credit_transactions",
    listRule: "wallet.workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    viewRule: "wallet.workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    createRule: null, // ledger writes happen server-side with the service credential
    updateRule: null,
    deleteRule: null,
    fields: [
      { type: "relation", name: "wallet", required: true, maxSelect: 1, collectionId: wallets.id, cascadeDelete: true },
      { type: "select", name: "type", required: true, maxSelect: 1, values: ["purchase", "bonus", "reservation", "consumption", "refund", "adjustment", "expiration"] },
      { type: "number", name: "amount", required: true },
      { type: "number", name: "balance_before", required: true },
      { type: "number", name: "balance_after", required: true },
      { type: "text", name: "reason", max: 1000 },
      { type: "relation", name: "job", maxSelect: 1, collectionId: jobsId },
      { type: "text", name: "reference", max: 200 },
      { type: "relation", name: "created_by", maxSelect: 1, collectionId: usersId },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
    indexes: [
      "CREATE INDEX idx_credit_transactions_wallet ON credit_transactions (wallet, created)",
      "CREATE INDEX idx_credit_transactions_reference ON credit_transactions (reference)",
    ],
  })
  app.save(transactions)

  const usage = new Collection({
    type: "base",
    name: "usage_events",
    listRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    viewRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    createRule: null,
    updateRule: null,
    deleteRule: null,
    fields: [
      { type: "relation", name: "workspace", required: true, maxSelect: 1, collectionId: workspacesId, cascadeDelete: true },
      { type: "relation", name: "job", maxSelect: 1, collectionId: jobsId },
      { type: "relation", name: "provider", maxSelect: 1, collectionId: providersId },
      { type: "relation", name: "model", maxSelect: 1, collectionId: modelsId },
      { type: "select", name: "event_type", required: true, maxSelect: 1, values: ["translation", "detection", "validation", "export", "other"] },
      { type: "number", name: "input_tokens" },
      { type: "number", name: "output_tokens" },
      { type: "number", name: "provider_cost" },
      { type: "number", name: "credits" },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
    indexes: ["CREATE INDEX idx_usage_events_workspace ON usage_events (workspace, created)"],
  })
  app.save(usage)
}, (app) => {
  app.delete(app.findCollectionByNameOrId("usage_events"))
  app.delete(app.findCollectionByNameOrId("credit_transactions"))
  app.delete(app.findCollectionByNameOrId("credit_wallets"))
})
