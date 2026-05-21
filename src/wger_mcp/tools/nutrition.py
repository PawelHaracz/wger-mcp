"""Nutrition plan / meal / diary tools."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..wger_client import WgerClient, WgerError
from .common import err


def register(mcp: FastMCP, client: WgerClient) -> None:
    @mcp.tool()
    async def list_nutrition_plans(
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
    ) -> list[dict[str, Any]]:
        """List your nutrition plans."""
        try:
            return await client.paginate("nutritionplan/", limit=limit)
        except WgerError as exc:
            return [err(exc)]

    @mcp.tool()
    async def get_nutrition_plan(plan_id: int) -> dict[str, Any]:
        """Fetch one nutrition plan with meals and items."""
        try:
            return await client.get(f"nutritionplan/{plan_id}/")
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def create_nutrition_plan(
        description: Annotated[str, Field(max_length=255)] = "",
        only_logging: bool = False,
        goal_energy: Annotated[float | None, Field(ge=0, le=20000)] = None,
        goal_protein: Annotated[float | None, Field(ge=0, le=2000)] = None,
        goal_carbohydrates: Annotated[float | None, Field(ge=0, le=2000)] = None,
        goal_fat: Annotated[float | None, Field(ge=0, le=2000)] = None,
    ) -> dict[str, Any]:
        """Create a nutrition plan. Returns the new plan including its id."""
        payload: dict[str, Any] = {
            "description": description,
            "only_logging": only_logging,
        }
        if goal_energy is not None:
            payload["goal_energy"] = goal_energy
        if goal_protein is not None:
            payload["goal_protein"] = goal_protein
        if goal_carbohydrates is not None:
            payload["goal_carbohydrates"] = goal_carbohydrates
        if goal_fat is not None:
            payload["goal_fat"] = goal_fat
        try:
            return await client.post("nutritionplan/", json=payload)
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def delete_nutrition_plan(plan_id: int) -> dict[str, Any]:
        """Delete a nutrition plan (cascades to its meals and diary entries)."""
        try:
            await client.delete(f"nutritionplan/{plan_id}/")
            return {"deleted": True, "plan_id": plan_id}
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def create_meal(
        plan_id: int,
        name: Annotated[str, Field(min_length=1, max_length=255)],
        order: Annotated[int, Field(ge=1, le=100)] = 1,
        time: str | None = None,
    ) -> dict[str, Any]:
        """Create a meal in a nutrition plan (e.g. Breakfast, Lunch).
        time is 'HH:MM' or 'HH:MM:SS'; omit for an unscheduled meal."""
        payload: dict[str, Any] = {
            "plan": plan_id,
            "name": name,
            "order": order,
        }
        if time is not None:
            payload["time"] = time
        try:
            return await client.post("meal/", json=payload)
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def log_ingredient(
        plan_id: int,
        ingredient_id: int,
        amount_g: Annotated[float, Field(gt=0, le=10000)],
        when: date | None = None,
    ) -> dict[str, Any]:
        """Log eaten food against a plan (logitem)."""
        payload = {
            "plan": plan_id,
            "ingredient": ingredient_id,
            "amount": amount_g,
            "datetime": f"{(when or date.today()).isoformat()}T12:00:00Z",
        }
        try:
            return await client.post("nutritiondiary/", json=payload)
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def list_log_items(
        when: date | None = None,
        plan_id: int | None = None,
        limit: Annotated[int, Field(ge=1, le=500)] = 200,
    ) -> list[dict[str, Any]]:
        """List nutrition-diary log items. Defaults to today; pass when=None
        with plan_id to scope by plan only."""
        params: dict[str, Any] = {"ordering": "-datetime"}
        if when is not None:
            params["datetime__date"] = when.isoformat()
        if plan_id is not None:
            params["plan"] = plan_id
        if when is None and plan_id is None:
            params["datetime__date"] = date.today().isoformat()
        try:
            return await client.paginate("nutritiondiary/", params=params, limit=limit)
        except WgerError as exc:
            return [err(exc)]

    @mcp.tool()
    async def delete_log_item(log_item_id: int) -> dict[str, Any]:
        """Delete a nutrition-diary log item (a logged ingredient entry)."""
        try:
            await client.delete(f"nutritiondiary/{log_item_id}/")
            return {"deleted": True, "log_item_id": log_item_id}
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def nutrition_summary(
        when: date | None = None,
        plan_id: int | None = None,
    ) -> dict[str, Any]:
        """Sum kcal/protein/carbs/fat from diary entries for a date. Per entry,
        fetches the ingredient's macros (per 100 g) and scales by amount_g."""
        target = (when or date.today()).isoformat()
        params: dict[str, Any] = {"datetime__date": target}
        if plan_id is not None:
            params["plan"] = plan_id
        try:
            entries = await client.paginate("nutritiondiary/", params=params, limit=500)
        except WgerError as exc:
            return err(exc)

        totals = {"kcal": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
        items: list[dict[str, Any]] = []
        cache: dict[int, dict[str, Any]] = {}
        for entry in entries:
            ing_id = entry.get("ingredient")
            amount = float(entry.get("amount") or 0)
            if not ing_id or amount <= 0:
                continue
            if ing_id not in cache:
                try:
                    cache[ing_id] = await client.get(f"ingredient/{ing_id}/")
                except WgerError as exc:
                    cache[ing_id] = {"_err": err(exc)}
            ing = cache[ing_id]
            if "_err" in ing:
                items.append({
                    "entry_id": entry.get("id"),
                    "ingredient_id": ing_id,
                    "error": ing["_err"],
                })
                continue
            factor = amount / 100.0
            kcal = float(ing.get("energy") or 0) * factor
            prot = float(ing.get("protein") or 0) * factor
            carb = float(ing.get("carbohydrates") or 0) * factor
            fat = float(ing.get("fat") or 0) * factor
            totals["kcal"] += kcal
            totals["protein_g"] += prot
            totals["carbs_g"] += carb
            totals["fat_g"] += fat
            items.append({
                "entry_id": entry.get("id"),
                "ingredient_id": ing_id,
                "ingredient_name": ing.get("name"),
                "amount_g": amount,
                "kcal": round(kcal, 1),
                "protein_g": round(prot, 1),
                "carbs_g": round(carb, 1),
                "fat_g": round(fat, 1),
            })
        return {
            "date": target,
            "totals": {k: round(v, 1) for k, v in totals.items()},
            "items": items,
        }
