"""Local-disk storage for expense receipt files.

Persistence model
-----------------
Receipts are written to a directory on the API host's local disk
(``RECEIPT_STORAGE_DIR``, default ``backend/app/var/receipts``). There is no
cloud object store or CDN. The operator is responsible for backing up that
directory together with the database; restoring only the database leaves
attachment rows whose files are missing (downloads return 404).

Safety
------
Storage keys are relative POSIX-style paths generated server-side. Every
resolved path is verified to stay under the storage root so a crafted key can
never read or write outside it. Client filenames are never used on disk.
"""

from __future__ import annotations

import uuid
from pathlib import Path, PurePosixPath

from app.core.config import get_settings
from app.core.errors import AppError, NotFoundError

ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/pdf": ".pdf",
}


def storage_root() -> Path:
    return Path(get_settings().receipt_storage_dir).resolve()


def max_bytes() -> int:
    return int(get_settings().receipt_max_bytes)


def extension_for(content_type: str) -> str:
    ext = ALLOWED_CONTENT_TYPES.get(content_type.strip().lower())
    if ext is None:
        raise AppError(
            "Receipt must be a JPEG, PNG, or PDF file.", code="receipt_bad_type", status_code=415
        )
    return ext


def validate_upload(content_type: str | None, size: int) -> str:
    """Validate type and size. Returns the normalized content type."""
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    extension_for(normalized)
    if size <= 0:
        raise AppError("Receipt file is empty.", code="receipt_empty")
    if size > max_bytes():
        raise AppError(
            f"Receipt exceeds the {max_bytes()} byte limit.",
            code="receipt_too_large",
            status_code=413,
        )
    return normalized


def build_storage_key(club_id: uuid.UUID, expense_id: uuid.UUID, ext: str) -> str:
    """Server-generated key: ``<club>/<expense>/<random><ext>`` (POSIX separators)."""
    clean_ext = ext if ext.startswith(".") else f".{ext}"
    if clean_ext.lower() not in set(ALLOWED_CONTENT_TYPES.values()):
        raise AppError("Unsupported receipt extension.", code="receipt_bad_type", status_code=415)
    return f"{club_id}/{expense_id}/{uuid.uuid4().hex}{clean_ext.lower()}"


def resolve_key(key: str) -> Path:
    """Map a storage key to an absolute path, refusing anything outside the root."""
    root = storage_root()
    posix = PurePosixPath(key)
    if not key or posix.is_absolute() or ".." in posix.parts or "\\" in key or ":" in key:
        raise AppError("Invalid receipt storage key.", code="receipt_bad_key")
    candidate = (root / Path(*posix.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise AppError("Invalid receipt storage key.", code="receipt_bad_key") from exc
    return candidate


def write_receipt(key: str, data: bytes) -> Path:
    path = resolve_key(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path


def read_receipt(key: str) -> bytes:
    path = resolve_key(key)
    if not path.is_file():
        raise NotFoundError("Receipt file not found.")
    return path.read_bytes()


def delete_receipt(key: str) -> None:
    """Best-effort removal; missing files are ignored."""
    try:
        path = resolve_key(key)
        path.unlink(missing_ok=True)
    except (AppError, OSError):
        return
