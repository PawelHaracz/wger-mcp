"""User-profile tools."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..config import Settings
from ..wger_client import WgerClient, WgerError
from .common import err


def register(mcp: FastMCP, client: WgerClient, settings: Settings) -> None:
    @mcp.tool()
    async def whoami() -> dict[str, Any]:
        """Return the wger user profile of the authenticated caller."""
        try:
            return await client.get("userprofile/")
        except WgerError as exc:
            return err(exc)
