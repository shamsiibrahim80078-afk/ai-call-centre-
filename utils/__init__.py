"""Shared utilities for the Autonomous Digital Workforce Platform."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def ensure_project_root_on_path() -> Path:
    """Ensure the repository root is importable when running modules as scripts."""
    root = str(PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    return PROJECT_ROOT


__all__ = ["PROJECT_ROOT", "ensure_project_root_on_path"]
