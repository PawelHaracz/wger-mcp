"""Body measurement tracking tools (categories + entries)."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..config import Settings
from ..wger_client import WgerClient, WgerError
from .common import bad_request, err


def register(mcp: FastMCP, client: WgerClient, settings: Settings) -> None:
    # ── Categories ──────────────────────────────────────────────────────────

    @mcp.tool()
    async def list_measurement_categories(
        limit: Annotated[int, Field(ge=1, le=500)] = 100,
    ) -> list[dict[str, Any]]:
        """List all body measurement categories (e.g. Waist, Chest, Bicep)."""
        try:
            return await client.paginate("measurement-category/", limit=limit)
        except WgerError as exc:
            return [err(exc)]

    @mcp.tool()
    async def create_measurement_category(
        name: Annotated[str, Field(min_length=1, max_length=100)],
        unit: Annotated[str, Field(min_length=1, max_length=10)] = "cm",
    ) -> dict[str, Any]:
        """Create a body measurement category (e.g. name='Bicep', unit='cm')."""
        try:
            return await client.post("measurement-category/", json={"name": name, "unit": unit})
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def get_measurement_category(category_id: str) -> dict[str, Any]:
        """Fetch a single measurement category by ID."""
        try:
            return await client.get(f"measurement-category/{category_id}/")
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def update_measurement_category(
        category_id: str,
        name: str | None = None,
        unit: Annotated[str | None, Field(max_length=10)] = None,
    ) -> dict[str, Any]:
        """Rename or change the unit of a measurement category."""
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if unit is not None:
            payload["unit"] = unit
        if not payload:
            return bad_request("no fields to update")
        try:
            return await client.patch(f"measurement-category/{category_id}/", json=payload)
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def delete_measurement_category(category_id: str) -> dict[str, Any]:
        """Delete a measurement category and all its entries."""
        try:
            await client.delete(f"measurement-category/{category_id}/")
            return {"deleted": True, "category_id": category_id}
        except WgerError as exc:
            return err(exc)

    # ── Entries ──────────────────────────────────────────────────────────────

    @mcp.tool()
    async def list_measurements(
        category_id: str | None = None,
        limit: Annotated[int, Field(ge=1, le=500)] = 100,
    ) -> list[dict[str, Any]]:
        """List body measurement entries, optionally filtered by category."""
        params: dict[str, Any] = {"ordering": "-date"}
        if category_id is not None:
            params["category"] = category_id
        try:
            return await client.paginate("measurement/", params=params, limit=limit)
        except WgerError as exc:
            return [err(exc)]

    @mcp.tool()
    async def log_measurement(
        category_id: str,
        value: Annotated[float, Field(gt=0)],
        when: date | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Add a body measurement entry to a category."""
        payload: dict[str, Any] = {
            "category": category_id,
            "value": value,
            "date": (when or date.today()).isoformat(),
        }
        if notes is not None:
            payload["notes"] = notes
        try:
            return await client.post("measurement/", json=payload)
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def get_measurement(measurement_id: str) -> dict[str, Any]:
        """Fetch a single body measurement entry by ID."""
        try:
            return await client.get(f"measurement/{measurement_id}/")
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def update_measurement(
        measurement_id: str,
        value: Annotated[float | None, Field(gt=0)] = None,
        when: date | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Patch a body measurement entry."""
        payload: dict[str, Any] = {}
        if value is not None:
            payload["value"] = value
        if when is not None:
            payload["date"] = when.isoformat()
        if notes is not None:
            payload["notes"] = notes
        if not payload:
            return bad_request("no fields to update")
        try:
            return await client.patch(f"measurement/{measurement_id}/", json=payload)
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def delete_measurement(measurement_id: str) -> dict[str, Any]:
        """Delete a body measurement entry."""
        try:
            await client.delete(f"measurement/{measurement_id}/")
            return {"deleted": True, "measurement_id": measurement_id}
        except WgerError as exc:
            return err(exc)
