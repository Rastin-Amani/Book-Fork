"""Symmetric encryption for secrets stored at rest.

Provider API keys and other per-user credentials must never be stored in
plaintext. They are encrypted with a key derived from ``ENCRYPTION_KEY`` and
decrypted only inside trusted server-side operations.
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.exceptions import ConfigurationError


def derive_fernet_key(secret: str) -> bytes:
    """Derive a valid 32-byte urlsafe Fernet key from an arbitrary secret.

    The configured ``ENCRYPTION_KEY`` may be raw text; we hash it to a stable
    32-byte key so operators are not forced to pre-generate a Fernet key.
    """
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


class SecretCipher:
    """Thin, typed wrapper around Fernet for encrypting stored secrets."""

    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    @classmethod
    def from_secret(cls, secret: str) -> SecretCipher:
        return cls(derive_fernet_key(secret))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise ConfigurationError(
                "Stored secret could not be decrypted with the configured key."
            ) from exc


@lru_cache(maxsize=1)
def generate_key() -> str:
    """Generate a fresh Fernet key (helper for ``scripts/`` and docs)."""
    return Fernet.generate_key().decode("ascii")
