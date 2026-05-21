"""Shared helpers for tool modules."""

from __future__ import annotations

from typing import Any

from ..wger_client import WgerError


def err(exc: WgerError) -> dict[str, Any]:
    """Shape a WgerError as a tool-response dict."""
    return {"error": True, "status": exc.status, "detail": exc.body}


def bad_request(detail: str) -> dict[str, Any]:
    """Shape a 400-style validation error as a tool-response dict."""
    return {"error": True, "status": 400, "detail": detail}
