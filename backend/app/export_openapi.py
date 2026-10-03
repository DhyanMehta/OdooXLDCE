"""Export OpenAPI schema to ``frontend/openapi.json`` without starting the server.

Does not open a database connection (lifespan is not run). For settings that
require ``DATABASE_URL`` outside development, set ``APP_ENV=development`` when
invoking this module so schema export stays offline-friendly.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _repo_paths() -> tuple[Path, Path]:
    backend_dir = Path(__file__).resolve().parents[1]
    repo_root = backend_dir.parent
    return backend_dir, repo_root / "frontend" / "openapi.json"


def export_openapi(dest: Path | None = None) -> Path:
    # Ensure Settings can load without a production DATABASE_URL during export.
    os.environ.setdefault("APP_ENV", "development")

    from app.main import app, assert_unique_operation_ids

    assert_unique_operation_ids(app)
    schema = app.openapi()
    # Deterministic JSON: sorted keys, stable separators, trailing newline.
    text = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    out = dest or _repo_paths()[1]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    return out


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    dest: Path | None = None
    if args:
        dest = Path(args[0])
    path = export_openapi(dest)
    print(f"Wrote OpenAPI schema to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
