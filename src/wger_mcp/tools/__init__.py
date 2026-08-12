"""MCP tool modules, grouped by domain.

Each module exposes a ``register(mcp, client, settings)`` function that attaches
its tools to the given FastMCP instance. ``server.build_app`` calls them all.
Modules that need no configuration simply ignore ``settings``.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ..config import Settings
from ..wger_client import WgerClient
from . import (
    analytics,
    body_weight,
    equipment,
    exercises,
    measurements,
    nutrition,
    off,
    profile,
    routines,
    workout_logs,
)

_REGISTRARS = (
    profile.register,
    routines.register,
    workout_logs.register,
    body_weight.register,
    measurements.register,
    equipment.register,
    nutrition.register,
    exercises.register,
    analytics.register,
    off.register,
)


def register_all(mcp: FastMCP, client: WgerClient, settings: Settings) -> None:
    """Register every tool module on the given FastMCP instance."""
    for register in _REGISTRARS:
        register(mcp, client, settings)


__all__ = ["register_all"]
