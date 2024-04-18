"""Server-side secret storage for provider connections.

The local-first application can persist provider API keys so the Settings page works
without editing `.env` by hand. Keys are encrypted at rest with Fernet. The encryption
key comes from ``AUDITOR_SECRET_KEY`` or a generated 0600 key file inside ``data/``.

This protects against casual disclosure (backups, exports, browser responses, logs). It
is **not** a hardware-backed vault: anyone who can read the application data directory
and the process environment can decrypt the keys. Use a real secret manager for shared
or production deployments.
"""

from __future__ import annotations

import base64
import hashlib
import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

ROOT = Path(__file__).resolve().parents[2]
KEY_PATH = ROOT / "data" / ".provider_key"


def _derived_key(raw: str) -> bytes:
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _load_or_create_key() -> bytes:
    env_key = os.getenv("AUDITOR_SECRET_KEY", "").strip()
    if env_key:
        return _derived_key(env_key)
    if KEY_PATH.exists():
        data = KEY_PATH.read_bytes().strip()
        try:
            Fernet(data)  # validate before use
            return data
        except (ValueError, InvalidToken):
            # A corrupt key must not silently produce undecryptable secrets.
            raise RuntimeError(
                "Provider key file is corrupt. Remove data/.provider_key to generate a new one "
                "or set AUDITOR_SECRET_KEY. Existing saved provider keys will need to be re-entered."
            ) from None
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    KEY_PATH.write_bytes(key)
    try:
        os.chmod(KEY_PATH, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return key


def _fernet() -> Fernet:
    return Fernet(_load_or_create_key())


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str | None) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        raise RuntimeError(
            "A saved provider key could not be decrypted. Re-enter it in Settings or restore "
            "the original AUDITOR_SECRET_KEY."
        ) from None


def mask_secret(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "••••"
    return f"••••{secret[-4:]}"
