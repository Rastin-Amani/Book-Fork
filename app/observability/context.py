"""Request/job correlation context.

The request id is stored in a :class:`contextvars.ContextVar` so it is available
to any coroutine in the same task (including downstream service calls). It is
also merged into structlog's contextvars so every log line carries it.

The inbound ``X-Request-ID`` header is **not** trusted for correlation (it would
let a client forge/poison correlation ids); the server always mints its own and
returns it to the client.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

import structlog

_request_id: ContextVar[str | None] = ContextVar("book_fork_request_id", default=None)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def set_request_id(request_id: str) -> str:
    """Bind ``request_id`` to the current context and structlog."""
    _request_id.set(request_id)
    structlog.contextvars.bind_contextvars(request_id=request_id)
    return request_id


def get_request_id() -> str | None:
    return _request_id.get()


def clear() -> None:
    _request_id.set(None)
    structlog.contextvars.clear_contextvars()
