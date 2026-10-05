// Worker/execution fields on translation_jobs: cooperative cancellation and
// translated-output metadata (never overwriting the source document).

migrate((app) => {
  const jobs = app.findCollectionByNameOrId("translation_jobs")
  jobs.fields.add(new BoolField({ name: "cancellation_requested" }))
  jobs.fields.add(new TextField({ name: "output_storage_key", max: 1000 }))
  jobs.fields.add(new TextField({ name: "output_checksum", max: 128 }))
  jobs.fields.add(new TextField({ name: "output_mime_type", max: 200 }))
  app.save(jobs)
}, (app) => {
  const jobs = app.findCollectionByNameOrId("translation_jobs")
  for (const name of [
    "cancellation_requested",
    "output_storage_key",
    "output_checksum",
    "output_mime_type",
  ]) {
    const field = jobs.fields.getByName(name)
    if (field) {
      jobs.fields.remove(field)
    }
  }
  app.save(jobs)
})
