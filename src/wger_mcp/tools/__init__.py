"""MCP tool modules, grouped by domain.

Each module exposes a ``register(mcp, client)`` function that attaches its
tools to the given FastMCP instance. ``server.build_app`` calls them all.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..wger_client import WgerClient
from . import (
    analytics,
    body_weight,
    exercises,
    nutrition,
    profile,
    routines,
    workout_logs,
)

_REGISTRARS = (
    profile.register,
    routines.register,
    workout_logs.register,
    body_weight.register,
    nutrition.register,
    exercises.register,
    analytics.register,
)


def register_all(mcp: FastMCP, client: WgerClient) -> None:
    """Register every tool module on the given FastMCP instance."""
    for register in _REGISTRARS:
        register(mcp, client)


__all__ = ["register_all"]
