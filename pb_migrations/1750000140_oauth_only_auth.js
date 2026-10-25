// OAuth-only sign-in (Google / GitHub).
//
// Passwords, OTP and MFA are disabled on the users collection, and direct REST
// account creation is blocked: a record can only be created by PocketBase's
// OAuth2 code exchange (context "oauth2"), which is how first-time sign-in
// works. Existing password records can no longer sign in.
//
// Provider ids/secrets are not schema: backup/restore them with the database,
// or apply them from the environment with `python scripts/configure_auth.py`.

migrate((app) => {
  const users = app.findCollectionByNameOrId("users")
  users.passwordAuth = { ...users.passwordAuth, enabled: false }
  users.otp = { ...users.otp, enabled: false }
  users.mfa = { ...users.mfa, enabled: false }
  users.createRule = '@request.context = "oauth2"'
  app.save(users)
}, (app) => {
  const users = app.findCollectionByNameOrId("users")
  users.passwordAuth = { ...users.passwordAuth, enabled: true }
  users.createRule = ""
  app.save(users)
})
