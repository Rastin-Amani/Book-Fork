"""Browser session handling.

The PocketBase bearer token is never exposed to JavaScript: it is encrypted
(Fernet, keyed by ``ENCRYPTION_KEY``) and stored in an HttpOnly cookie. Fernet
ciphertext is authenticated, so the cookie is also tamper-proof.
"""

from __future__ import annotations

from starlette.responses import Response

from app.security.crypto import SecretCipher


class SessionManager:
    """Encodes/decodes the session cookie and applies cookie flags."""

    def __init__(
        self,
        cipher: SecretCipher,
        *,
        cookie_name: str,
        max_age_seconds: int,
        secure: bool,
        samesite: str = "lax",
        domain: str | None = None,
    ) -> None:
        self._cipher = cipher
        self.cookie_name = cookie_name
        self._max_age = max_age_seconds
        self._secure = secure
        self._samesite = samesite
        self._domain = domain

    def encode(self, token: str) -> str:
        return self._cipher.encrypt(token)

    def decode(self, cookie_value: str | None) -> str | None:
        if not cookie_value:
            return None
        try:
            return self._cipher.decrypt(cookie_value)
        except Exception:
            return None

    def set_cookie(self, response: Response, token: str) -> None:
        response.set_cookie(
            key=self.cookie_name,
            value=self.encode(token),
            max_age=self._max_age,
            httponly=True,
            secure=self._secure,
            samesite=self._samesite,  # type: ignore[arg-type]
            domain=self._domain,
            path="/",
        )

    def clear_cookie(self, response: Response) -> None:
        response.delete_cookie(
            key=self.cookie_name,
            httponly=True,
            secure=self._secure,
            samesite=self._samesite,  # type: ignore[arg-type]
            domain=self._domain,
            path="/",
        )
