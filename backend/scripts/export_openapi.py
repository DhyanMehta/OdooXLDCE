"""CLI wrapper: ``python scripts/export_openapi.py [dest]``."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow ``python scripts/export_openapi.py`` from backend/ without install.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.export_openapi import main

if __name__ == "__main__":
    raise SystemExit(main())
