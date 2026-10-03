"""Owner-display QR credentials.

Design
------
Check-in uses a SHA-256 hash of the raw token (see ``hash_token``).
Owner re-display needs the raw token again, so we store an *encrypted*
blob — Fernet (AES-128-CBC + HMAC) — not a signed-only serializer.

Legacy rows sealed with itsdangerous ``URLSafeSerializer`` (prefix-free)
remain readable for one compatibility generation; new seals use the
``enc:v1:`` prefix. Rotate by setting ``QR_CREDENTIAL_KEY`` (or rotating
``SECRET_KEY`` and re-encrypting) — old Fernet keys cannot decrypt new ones.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from itsdangerous import BadSignature, URLSafeSerializer

from app.core.config import get_settings

_LEGACY_SALT = "campusos-qr"
_AEAD_PREFIX = "enc:v1:"


def _fernet_key_from_secret(secret: str) -> bytes:
    # Fernet requires a url-safe base64-encoded 32-byte key.
    digest = hashlib.sha256(f"campusos-qr-aead:{secret}".encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _fernets() -> MultiFernet:
    settings = get_settings()
    keys: list[bytes] = []
    if settings.qr_credential_key:
        keys.append(_fernet_key_from_secret(settings.qr_credential_key))
    # Always include SECRET_KEY-derived key so unset QR_CREDENTIAL_KEY still works,
    # and rotation can keep both temporarily.
    keys.append(_fernet_key_from_secret(settings.secret_key))
    # Deduplicate while preserving order (primary first).
    unique: list[bytes] = []
    for key in keys:
        if key not in unique:
            unique.append(key)
    return MultiFernet([Fernet(k) for k in unique])


def _legacy_serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().secret_key, salt=_LEGACY_SALT)


def seal_token(raw: str) -> str:
    """Authenticated-encrypt a raw QR token for owner redisplay."""
    token = _fernets().encrypt(raw.encode("utf-8")).decode("ascii")
    return f"{_AEAD_PREFIX}{token}"


def unseal_token(sealed: str) -> str | None:
    """Decrypt an AEAD seal, or fall back to legacy signed-only seals."""
    if sealed.startswith(_AEAD_PREFIX):
        blob = sealed[len(_AEAD_PREFIX) :].encode("ascii")
        try:
            return _fernets().decrypt(blob).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError):
            return None
    # Compatibility path for tickets issued before AEAD migration.
    try:
        value = _legacy_serializer().loads(sealed)
    except BadSignature:
        return None
    return value if isinstance(value, str) else None
