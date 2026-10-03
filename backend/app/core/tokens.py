"""Seal/unseal owner-display tokens without storing plaintext QR values."""

from __future__ import annotations

from itsdangerous import BadSignature, URLSafeSerializer

from app.core.config import get_settings


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().secret_key, salt="campusos-qr")


def seal_token(raw: str) -> str:
    return _serializer().dumps(raw)


def unseal_token(sealed: str) -> str | None:
    try:
        value = _serializer().loads(sealed)
    except BadSignature:
        return None
    return value if isinstance(value, str) else None
