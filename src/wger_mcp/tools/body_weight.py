"""Body-weight tracking tools."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..wger_client import WgerClient, WgerError
from .common import bad_request, err


def register(mcp: FastMCP, client: WgerClient) -> None:
    @mcp.tool()
    async def log_body_weight(
        weight_kg: Annotated[float, Field(gt=0, le=500)],
        when: date | None = None,
    ) -> dict[str, Any]:
        """Log a body-weight entry."""
        payload = {
            "weight": weight_kg,
            "date": (when or date.today()).isoformat(),
        }
        try:
            return await client.post("weightentry/", json=payload)
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def get_body_weight_history(
        limit: Annotated[int, Field(ge=1, le=500)] = 30,
    ) -> list[dict[str, Any]]:
        """Return recent body-weight entries (newest first)."""
        try:
            return await client.paginate(
                "weightentry/", params={"ordering": "-date"}, limit=limit
            )
        except WgerError as exc:
            return [err(exc)]

    @mcp.tool()
    async def update_body_weight_entry(
        entry_id: int,
        weight_kg: Annotated[float | None, Field(gt=0, le=500)] = None,
        when: date | None = None,
    ) -> dict[str, Any]:
        """Patch a body-weight entry."""
        payload: dict[str, Any] = {}
        if weight_kg is not None:
            payload["weight"] = weight_kg
        if when is not None:
            payload["date"] = when.isoformat()
        if not payload:
            return bad_request("no fields to update")
        try:
            return await client.patch(f"weightentry/{entry_id}/", json=payload)
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def delete_body_weight_entry(entry_id: int) -> dict[str, Any]:
        """Delete a body-weight entry."""
        try:
            await client.delete(f"weightentry/{entry_id}/")
            return {"deleted": True, "entry_id": entry_id}
        except WgerError as exc:
            return err(exc)
