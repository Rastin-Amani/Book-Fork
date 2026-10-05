"""Unit tests for cryptographic secret handling."""

from __future__ import annotations

import pytest
from app.exceptions import ConfigurationError
from app.security.crypto import SecretCipher, derive_fernet_key


def test_encrypt_decrypt_roundtrip() -> None:
    cipher = SecretCipher.from_secret("a-strong-secret")
    token = cipher.encrypt("sk-provider-api-key")
    assert token != "sk-provider-api-key"
    assert cipher.decrypt(token) == "sk-provider-api-key"


def test_derived_key_is_stable_and_distinct() -> None:
    assert derive_fernet_key("abc") == derive_fernet_key("abc")
    assert derive_fernet_key("abc") != derive_fernet_key("abd")


def test_decrypt_with_wrong_key_fails() -> None:
    token = SecretCipher.from_secret("key-one").encrypt("value")
    with pytest.raises(ConfigurationError):
        SecretCipher.from_secret("key-two").decrypt(token)
