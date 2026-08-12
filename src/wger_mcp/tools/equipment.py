"""Gym equipment CRUD tools."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..config import Settings
from ..wger_client import WgerClient, WgerError
from .common import err


def register(mcp: FastMCP, client: WgerClient, settings: Settings) -> None:
    @mcp.tool()
    async def list_gym_equipment(
        limit: Annotated[int, Field(ge=1, le=500)] = 100,
    ) -> list[dict[str, Any]]:
        """List all available equipment entries (global + custom)."""
        try:
            return await client.paginate("equipment/", limit=limit)
        except WgerError as exc:
            return [err(exc)]

    @mcp.tool()
    async def get_gym_equipment(equipment_id: str) -> dict[str, Any]:
        """Fetch a single equipment entry by ID."""
        try:
            return await client.get(f"equipment/{equipment_id}/")
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def create_gym_equipment(
        name: Annotated[str, Field(min_length=1, max_length=100)],
    ) -> dict[str, Any]:
        """Create a custom equipment entry (e.g. 'Cable machine', 'Resistance band')."""
        try:
            return await client.post("equipment/", json={"name": name})
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def update_gym_equipment(
        equipment_id: str,
        name: Annotated[str, Field(min_length=1, max_length=100)],
    ) -> dict[str, Any]:
        """Rename an equipment entry."""
        try:
            return await client.patch(f"equipment/{equipment_id}/", json={"name": name})
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def delete_gym_equipment(equipment_id: str) -> dict[str, Any]:
        """Delete an equipment entry."""
        try:
            await client.delete(f"equipment/{equipment_id}/")
            return {"deleted": True, "equipment_id": equipment_id}
        except WgerError as exc:
            return err(exc)
