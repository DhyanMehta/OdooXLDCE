"""Password hashing and opaque token helpers."""

from __future__ import annotations

import hashlib
import secrets

from pwdlib import PasswordHash

_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hash.verify(password, password_hash)


def generate_token(nbytes: int = 32) -> str:
    """Return an unpredictable URL-safe token."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Store only hashes of session/QR/unsubscribe tokens."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
