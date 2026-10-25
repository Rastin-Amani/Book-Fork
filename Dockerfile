# syntax=docker/dockerfile:1

# --- Stage 1: build frontend assets (Tailwind + daisyUI + vendored JS) --------
FROM node:24-bookworm-slim AS assets
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY scripts/vendor-assets.mjs ./scripts/
COPY static/css/input.css ./static/css/input.css
COPY templates ./templates
COPY app ./app
RUN npm run build

# --- Stage 2: Python runtime --------------------------------------------------
FROM python:3.14-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/app/.cache/uv
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY worker ./worker
COPY templates ./templates
COPY static ./static
COPY seeds ./seeds
COPY pb_migrations ./pb_migrations
COPY --from=assets /app/static/css/app.css ./static/css/app.css
COPY --from=assets /app/static/js/vendor ./static/js/vendor

RUN uv sync --frozen --no-dev

# Run as a non-root user. The runtime cache lives under /app so `uv run` has a
# writable cache without a home directory.
RUN useradd --system --uid 1001 book-fork \
    && rm -rf /app/.cache \
    && mkdir -p /app/.cache/uv \
    && chown -R book-fork:book-fork /app
USER book-fork

EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
