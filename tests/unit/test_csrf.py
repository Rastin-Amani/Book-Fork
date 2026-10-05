"""Unit tests for CSRF token issue/validate."""

from __future__ import annotations

from app.security.csrf import CsrfManager


def test_valid_double_submit() -> None:
    manager = CsrfManager("secret")
    token = manager.issue()
    assert manager.is_valid(token, token)


def test_rejects_missing_tokens() -> None:
    manager = CsrfManager("secret")
    token = manager.issue()
    assert not manager.is_valid(None, token)
    assert not manager.is_valid(token, None)


def test_rejects_mismatched_pair() -> None:
    manager = CsrfManager("secret")
    assert not manager.is_valid(manager.issue(), manager.issue())


def test_rejects_forged_token() -> None:
    manager = CsrfManager("secret")
    assert not manager.is_valid("not-a-real-token", "not-a-real-token")


def test_rejects_token_from_other_secret() -> None:
    attacker = CsrfManager("other-secret").issue()
    assert not CsrfManager("secret").is_valid(attacker, attacker)
