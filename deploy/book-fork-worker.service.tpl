[Unit]
Description=Book Fork — Worker process (durable translation engine)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=__USER__
WorkingDirectory=__ROOT__
# Config is pydantic-settings: it reads .env from the working directory, which
# includes POCKETBASE_SERVICE_CREDENTIAL — required or the worker refuses to
# start. The worker is independent of the web process and claims jobs from
# PocketBase with per-job leases, so it is safe to restart or run several.
ExecStart=__ROOT__/.venv/bin/python -m worker.main
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
