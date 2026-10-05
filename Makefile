.PHONY: install install-js build css css-watch seed web worker test lint format typecheck check \
	install-web-service install-worker-service

# The project interpreter lives in .venv — bare `python` is not on PATH on a
# fresh server, so every target resolves it explicitly. Config is
# pydantic-settings: both the web and worker processes load `.env` from the
# working directory, so run targets from the project root.
PY := .venv/bin/python

install:
	uv sync
	npm install

install-js:
	npm install

build:
	npm run build

css:
	npm run build:css

css-watch:
	npm run dev:css

seed:
	$(PY) scripts/seed.py

web:
	$(PY) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker:
	$(PY) -m worker.main

# Process at most one queued job, then exit (useful for debugging).
worker-once:
	$(PY) -m worker.main --once

test:
	$(PY) -m pytest

lint:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .

format:
	.venv/bin/ruff format .

typecheck:
	$(PY) -m mypy .

check: lint typecheck test

# systemd services (run the web and worker as managed services on this host).
# The worker and web are independent processes; the worker claims jobs from
# PocketBase, so it can be restarted or scaled without touching the web tier.
install-worker-service:
	@echo "Installing book-fork-worker.service for user $(USER)…"
	@sed -e "s/__USER__/$(USER)/g" -e "s|__ROOT__|$(CURDIR)|g" deploy/book-fork-worker.service.tpl | sudo tee /etc/systemd/system/book-fork-worker.service > /dev/null
	sudo systemctl daemon-reload
	sudo systemctl enable --now book-fork-worker
	@echo "book-fork-worker installed. Logs: journalctl -u book-fork-worker -f"

install-web-service:
	@echo "Installing book-fork-web.service for user $(USER)…"
	@sed -e "s/__USER__/$(USER)/g" -e "s|__ROOT__|$(CURDIR)|g" deploy/book-fork-web.service.tpl | sudo tee /etc/systemd/system/book-fork-web.service > /dev/null
	sudo systemctl daemon-reload
	sudo systemctl enable --now book-fork-web
	@echo "book-fork-web installed. Logs: journalctl -u book-fork-web -f"
