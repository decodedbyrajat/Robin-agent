"""Shared helpers for direct xAI HTTP integrations."""

from __future__ import annotations


def robin_xai_user_agent() -> str:
    """Return a stable Robin-specific User-Agent for xAI HTTP calls."""
    try:
        from robin_cli import __version__
    except Exception:
        __version__ = "unknown"
    return f"Robin-Agent/{__version__}"
