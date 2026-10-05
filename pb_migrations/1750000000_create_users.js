// Ensures the built-in `users` auth collection carries Book Fork's authorization
// rules. PocketBase 0.40+ ships a default `users` auth collection (with id,
// password, tokenKey, email, emailVisibility, verified, name, avatar, created,
// updated), so this migration must NOT create it — it only normalizes rules.

migrate((app) => {
  const users = app.findCollectionByNameOrId("users")

  users.listRule = "id = @request.auth.id"
  users.viewRule = "id = @request.auth.id"
  users.createRule = "" // public self-service signup
  users.updateRule = "id = @request.auth.id"
  users.deleteRule = "id = @request.auth.id"

  app.save(users)
}, (app) => {
  // Non-destructive: leave the built-in collection in place.
})
