// Allow a workspace owner to create the first membership row for their own
// workspace (needed for personal-workspace bootstrap under user-token rules).

migrate((app) => {
  const members = app.findCollectionByNameOrId("workspace_members")
  members.createRule =
    "workspace.owner ?= @request.auth.id || workspace.workspace_members_via_workspace.user ?= @request.auth.id"
  app.save(members)
}, (app) => {
  const members = app.findCollectionByNameOrId("workspace_members")
  members.createRule = "workspace.workspace_members_via_workspace.user ?= @request.auth.id"
  app.save(members)
})
