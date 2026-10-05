"""Generate development secrets for `.env`.

Usage::

    uv run python scripts/generate_secrets.py
"""

from __future__ import annotations

import secrets

from cryptography.fernet import Fernet


def main() -> None:
    print(f"APP_SECRET_KEY={secrets.token_urlsafe(48)}")
    print(f"ENCRYPTION_KEY={Fernet.generate_key().decode('ascii')}")
    print(f"WORKER_INTERNAL_TOKEN={secrets.token_urlsafe(48)}")


if __name__ == "__main__":
    main()
