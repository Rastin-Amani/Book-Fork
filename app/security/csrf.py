"""CSRF protection for cookie-authenticated browser mutations.

Strategy: **signed double-submit token**.

* The server issues a signed token and stores it in a non-HttpOnly ``SameSite``
  cookie so HTMX can read it and echo it back.
* State-changing requests must present the same token via the ``X-CSRF-Token``
  header (HTMX adds it globally) or a ``csrf_token`` form field.
* The token signature is verified, so an attacker cannot mint a valid token.

The token is additionally bound to the value stored in the cookie (double
submit); it is not bound to the server session, which is an accepted trade-off
for this architecture.
``# ponytail: signed double-submit; bind to session id later if required``
"""

from __future__ import annotations

import hmac
import secrets

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

CSRF_COOKIE_NAME = "book_fork_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_FORM_FIELD = "csrf_token"
CSRF_MAX_AGE_SECONDS = 60 * 60 * 8


class CsrfManager:
    """Issues and validates signed CSRF tokens."""

    def __init__(self, secret_key: str, *, max_age_seconds: int = CSRF_MAX_AGE_SECONDS) -> None:
        self._serializer = URLSafeTimedSerializer(secret_key, salt="book-fork-csrf")
        self._max_age = max_age_seconds

    def issue(self) -> str:
        """Create a new signed token."""
        return self._serializer.dumps(secrets.token_urlsafe(24))

    def is_valid(self, token: str | None, cookie_token: str | None) -> bool:
        """Validate a presented token against the stored cookie token."""
        if not token or not cookie_token:
            return False
        if not hmac.compare_digest(token, cookie_token):
            return False
        try:
            self._serializer.loads(token, max_age=self._max_age)
        except BadSignature, SignatureExpired:
            return False
        return True
