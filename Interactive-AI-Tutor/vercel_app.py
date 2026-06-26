"""
Vercel entrypoint shim. Vercel's Python runtime imports `app` from a module
path (configured via pyproject.toml's tool.vercel.entrypoint), running with
the project root as the working directory. The actual app's internal modules
use absolute imports like `from app.config... import ...` (i.e. they expect
backend/ itself, not the project root, to be on sys.path — this matches how
local dev runs it via `uvicorn app.main:app --app-dir backend`). This shim
adds backend/ to sys.path before importing, so those imports keep working
unchanged on Vercel without rewriting every internal import across the app.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.main import app  # noqa: E402

__all__ = ["app"]
