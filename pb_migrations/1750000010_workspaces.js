// Workspaces and membership: the ownership boundary for every user-owned
// object. Backend authorization is enforced here (PocketBase rules) in addition
// to application-level checks.

const AUTODATE = [
  { type: "autodate", name: "created", onCreate: true, onUpdate: false },
  { type: "autodate", name: "updated", onCreate: true, onUpdate: true },
]

migrate((app) => {
  const usersId = app.findCollectionByNameOrId("users").id

  const workspaces = new Collection({
    type: "base",
    name: "workspaces",
    // Provisional owner-only rules; membership-based rules are added below,
    // once workspace_members exists (back-relations can't be resolved before).
    listRule: "owner ?= @request.auth.id",
    viewRule: "owner ?= @request.auth.id",
    createRule: "@request.auth.id != ''",
    updateRule: "owner ?= @request.auth.id",
    deleteRule: "owner ?= @request.auth.id",
    fields: [
      { type: "text", name: "name", required: true, max: 200 },
      { type: "text", name: "slug", required: true, max: 120 },
      { type: "relation", name: "owner", required: true, maxSelect: 1, collectionId: usersId },
      { type: "text", name: "plan", max: 50 },
      { type: "json", name: "metadata", maxSize: 2000000 },
      ...AUTODATE,
    ],
    indexes: ["CREATE UNIQUE INDEX idx_workspaces_slug ON workspaces (slug)"],
  })
  app.save(workspaces)

  const members = new Collection({
    type: "base",
    name: "workspace_members",
    listRule: "user ?= @request.auth.id || workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    viewRule: "user ?= @request.auth.id || workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    createRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    updateRule: "workspace.workspace_members_via_workspace.user ?= @request.auth.id",
    deleteRule: "workspace.owner ?= @request.auth.id",
    fields: [
      { type: "relation", name: "workspace", required: true, maxSelect: 1, collectionId: workspaces.id, cascadeDelete: true },
      { type: "relation", name: "user", required: true, maxSelect: 1, collectionId: usersId, cascadeDelete: true },
      { type: "select", name: "role", required: true, maxSelect: 1, values: ["owner", "admin", "member", "viewer"] },
      ...AUTODATE,
    ],
    indexes: [
      "CREATE UNIQUE INDEX idx_workspace_members_unique ON workspace_members (workspace, user)",
      "CREATE INDEX idx_workspace_members_user ON workspace_members (user)",
    ],
  })
  app.save(members)

  // Now that the back-relation exists, allow members to see their workspaces.
  workspaces.listRule = "owner ?= @request.auth.id || workspace_members_via_workspace.user ?= @request.auth.id"
  workspaces.viewRule = "owner ?= @request.auth.id || workspace_members_via_workspace.user ?= @request.auth.id"
  app.save(workspaces)
}, (app) => {
  app.delete(app.findCollectionByNameOrId("workspace_members"))
  app.delete(app.findCollectionByNameOrId("workspaces"))
})
