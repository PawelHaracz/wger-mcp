"""User-profile tools."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..wger_client import WgerClient, WgerError
from .common import err


def register(mcp: FastMCP, client: WgerClient) -> None:
    @mcp.tool()
    async def whoami() -> dict[str, Any]:
        """Return the wger user profile bound to the configured API token."""
        try:
            return await client.get("userprofile/")
        except WgerError as exc:
            return err(exc)
