"""Conflict-free mirror module for sasha_identity.

This file is intentionally separate from `script.py` so edits can happen
without touching the primary extension entrypoint.
"""

from __future__ import annotations

# Re-export core extension symbols from the primary implementation.
from .script import params, ui  # noqa: F401
