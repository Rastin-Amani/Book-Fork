// Phase 6: pricing, billing mode, credit/provider-cost tracking, economy tier.

migrate((app) => {
  const models = app.findCollectionByNameOrId("provider_models")
  models.fields.add(new NumberField({ name: "request_cost" }))
  app.save(models)

  const connections = app.findCollectionByNameOrId("provider_connections")
  connections.fields.add(
    new SelectField({ name: "billing_mode", maxSelect: 1, values: ["managed", "own_api"] })
  )
  app.save(connections)

  const jobs = app.findCollectionByNameOrId("translation_jobs")
  jobs.fields.add(new NumberField({ name: "estimated_credits" }))
  jobs.fields.add(new NumberField({ name: "estimated_provider_cost" }))
  jobs.fields.add(new NumberField({ name: "actual_provider_cost" }))
  app.save(jobs)

  for (const name of ["translation_profiles", "translation_jobs"]) {
    const collection = app.findCollectionByNameOrId(name)
    const field = collection.fields.getByName("quality_mode")
    if (field && !field.values.includes("economy")) {
      field.values.push("economy")
      app.save(collection)
    }
  }
}, (app) => {
  for (const name of ["translation_profiles", "translation_jobs"]) {
    const collection = app.findCollectionByNameOrId(name)
    const field = collection.fields.getByName("quality_mode")
    if (field) {
      field.values = field.values.filter((value) => value !== "economy")
      app.save(collection)
    }
  }
  const jobs = app.findCollectionByNameOrId("translation_jobs")
  for (const name of ["estimated_credits", "estimated_provider_cost", "actual_provider_cost"]) {
    const field = jobs.fields.getByName(name)
    if (field) {
      jobs.fields.remove(field)
    }
  }
  app.save(jobs)

  const connections = app.findCollectionByNameOrId("provider_connections")
  const billing = connections.fields.getByName("billing_mode")
  if (billing) {
    connections.fields.remove(billing)
  }
  app.save(connections)

  const models = app.findCollectionByNameOrId("provider_models")
  const requestCost = models.fields.getByName("request_cost")
  if (requestCost) {
    models.fields.remove(requestCost)
  }
  app.save(models)
})
