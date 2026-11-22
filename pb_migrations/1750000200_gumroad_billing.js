// Gumroad billing: correlation token, subscription reference, refund marker.
//
// This migration is additive. Historical PayRam invoices and events stay
// readable: `payram` remains a valid provider value and the old columns are
// untouched. New Gumroad checkouts are correlated by a high-entropy token in a
// Gumroad custom field, never by email or amount.

migrate((app) => {
  const invoices = app.findCollectionByNameOrId("billing_invoices")

  const provider = invoices.fields.getByName("provider")
  if (!provider.values.includes("gumroad")) {
    provider.values.push("gumroad")
  }
  if (!invoices.fields.getByName("correlation_token")) {
    invoices.fields.add(new TextField({ name: "correlation_token", max: 200 }))
  }
  if (!invoices.fields.getByName("provider_subscription_id")) {
    invoices.fields.add(new TextField({ name: "provider_subscription_id", max: 200 }))
  }
  if (!invoices.fields.getByName("refunded_at")) {
    invoices.fields.add(new DateField({ name: "refunded_at" }))
  }
  invoices.indexes = invoices.indexes.concat([
    "CREATE UNIQUE INDEX idx_billing_invoices_correlation ON billing_invoices (correlation_token) WHERE correlation_token != ''",
    // A sale id is one payment and is unique (base migration). A subscription
    // id is indexed, not unique: one membership can legitimately pay for more
    // than one invoice.
    "CREATE INDEX idx_billing_invoices_subscription ON billing_invoices (provider_subscription_id)",
  ])
  app.save(invoices)

  const events = app.findCollectionByNameOrId("billing_events")
  const eventType = events.fields.getByName("event_type")
  for (const value of [
    "sale",
    "refund",
    "dispute",
    "dispute_won",
    "subscription_updated",
    "subscription_ended",
    "subscription_restarted",
  ]) {
    if (!eventType.values.includes(value)) {
      eventType.values.push(value)
    }
  }
  app.save(events)
}, (app) => {
  const invoices = app.findCollectionByNameOrId("billing_invoices")
  invoices.indexes = invoices.indexes.filter(
    (index) =>
      !index.includes("idx_billing_invoices_correlation") &&
      !index.includes("idx_billing_invoices_subscription")
  )
  invoices.fields.removeByName("refunded_at")
  invoices.fields.removeByName("provider_subscription_id")
  invoices.fields.removeByName("correlation_token")
  // The `gumroad` provider value is intentionally left in place: removing a
  // select value while records still reference it would corrupt them.
  app.save(invoices)

  // Event type values are left as a superset for the same reason.
})
