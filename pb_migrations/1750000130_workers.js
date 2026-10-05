// Worker liveness records. Written only by the worker (service token); used by
// health checks and the admin area to distinguish "process alive" from
// "worker alive". Admin-only (null rules => superuser/service token).

migrate((app) => {
  const collection = new Collection({
    type: "base",
    name: "workers",
    listRule: null,
    viewRule: null,
    createRule: null,
    updateRule: null,
    deleteRule: null,
    fields: [
      { name: "worker_id", type: "text", required: true, max: 200 },
      { name: "host", type: "text", max: 200 },
      { name: "pid", type: "number" },
      { name: "status", type: "text", max: 40 },
      { name: "version", type: "text", max: 40 },
      { name: "current_jobs", type: "number" },
      { name: "started_at", type: "date" },
      { name: "last_heartbeat", type: "date" },
      { name: "metadata", type: "json", maxSize: 200000 },
    ],
    indexes: ["CREATE UNIQUE INDEX idx_workers_worker_id ON workers (worker_id)"],
  })
  app.save(collection)
}, (app) => {
  const collection = app.findCollectionByNameOrId("workers")
  app.delete(collection)
})
