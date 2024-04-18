"""Streamlit page modules.

Each module exposes ``render()`` and performs no work at import time. Keeping pages
separate makes the UI navigable and prevents the monolithic conditional block that the
prototype used.
"""

from __future__ import annotations

__all__ = [
    "analytics",
    "batch",
    "comparison",
    "escalations",
    "overview",
    "policies",
    "reviews",
    "scenarios",
    "settings",
    "single_audit",
]
