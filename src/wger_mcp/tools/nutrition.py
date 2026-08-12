"""Nutrition plan / meal / diary tools."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..config import Settings
from ..wger_client import WgerClient, WgerError
from .common import bad_request, err

_INGREDIENT_CONCURRENCY = 8

# Time of day used when a caller supplies a bare date for a diary entry. wger
# stores diary entries as a full timestamp, so a date alone has to land
# somewhere; noon keeps the entry on the intended day in either direction under
# a timezone shift, which midnight would not.
_BARE_DATE_TIME = time(12, 0)


def _diary_timestamp(when: date | datetime | None) -> str | None:
    """Normalise a diary ``when`` argument to what wger's ``datetime`` expects.

    ``None`` returns ``None`` so the caller can omit the field entirely and let
    wger apply its own ``timezone.now`` default. A ``datetime`` is preserved
    exactly, including any timezone offset. A bare ``date`` is anchored at
    :data:`_BARE_DATE_TIME`.

    Note ``datetime`` is a subclass of ``date``, so the subclass is checked
    first.
    """
    if when is None:
        return None
    if isinstance(when, datetime):
        return when.isoformat()
    return datetime.combine(when, _BARE_DATE_TIME).isoformat()


def register(mcp: FastMCP, client: WgerClient, settings: Settings) -> None:
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
    async def get_nutrition_plan(plan_id: str) -> dict[str, Any]:
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
    async def update_nutrition_plan(
        plan_id: str,
        description: Annotated[str | None, Field(max_length=255)] = None,
        only_logging: bool | None = None,
        goal_energy: Annotated[float | None, Field(ge=0, le=20000)] = None,
        goal_protein: Annotated[float | None, Field(ge=0, le=2000)] = None,
        goal_carbohydrates: Annotated[float | None, Field(ge=0, le=2000)] = None,
        goal_fat: Annotated[float | None, Field(ge=0, le=2000)] = None,
    ) -> dict[str, Any]:
        """Patch a nutrition plan. Only provided fields are sent."""
        payload: dict[str, Any] = {}
        if description is not None:
            payload["description"] = description
        if only_logging is not None:
            payload["only_logging"] = only_logging
        if goal_energy is not None:
            payload["goal_energy"] = goal_energy
        if goal_protein is not None:
            payload["goal_protein"] = goal_protein
        if goal_carbohydrates is not None:
            payload["goal_carbohydrates"] = goal_carbohydrates
        if goal_fat is not None:
            payload["goal_fat"] = goal_fat
        if not payload:
            return bad_request("no fields to update")
        try:
            return await client.patch(f"nutritionplan/{plan_id}/", json=payload)
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def delete_nutrition_plan(plan_id: str) -> dict[str, Any]:
        """Delete a nutrition plan (cascades to its meals and diary entries)."""
        try:
            await client.delete(f"nutritionplan/{plan_id}/")
            return {"deleted": True, "plan_id": plan_id}
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def create_meal(
        plan_id: str,
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

    # Recipes — wger has no dedicated Recipe entity, so a "recipe" is modelled
    # as a Meal inside a NutritionPlan, with its MealItems acting as the
    # recipe's ingredients. create_recipe / get_recipe / add_ingredient_to_recipe
    # are semantic aliases over the meal + mealitem endpoints.

    @mcp.tool()
    async def create_recipe(
        plan_id: str,
        name: Annotated[str, Field(min_length=1, max_length=255)],
        order: Annotated[int, Field(ge=1, le=100)] = 1,
    ) -> dict[str, Any]:
        """Create a recipe (a named Meal inside a plan). Wger has no separate
        Recipe model, so this is a thin alias over POST /meal/ — the returned
        id is a meal_id, usable wherever meal_id is expected."""
        try:
            return await client.post(
                "meal/", json={"plan": plan_id, "name": name, "order": order}
            )
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def get_recipe(recipe_id: str) -> dict[str, Any]:
        """Fetch a recipe (Meal) with its items. recipe_id = meal id."""
        try:
            return await client.get(f"meal/{recipe_id}/")
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def add_ingredient_to_recipe(
        recipe_id: str,
        ingredient_id: str,
        amount_g: Annotated[float, Field(gt=0, le=10000)],
        order: Annotated[int, Field(ge=1, le=200)] = 1,
        weight_unit_id: str | None = None,
    ) -> dict[str, Any]:
        """Add an ingredient to a recipe (POST /mealitem/). amount_g is in
        grams unless weight_unit_id is supplied (custom unit)."""
        payload: dict[str, Any] = {
            "meal": recipe_id,
            "ingredient": ingredient_id,
            "amount": amount_g,
            "order": order,
        }
        if weight_unit_id is not None:
            payload["weight_unit"] = weight_unit_id
        try:
            return await client.post("mealitem/", json=payload)
        except WgerError as exc:
            return err(exc)

    # Note: wger's REST /ingredient/ endpoint is read-only (ReadOnlyModelViewSet).
    # Custom-ingredient submission previously went through wger's Django web form
    # with username/password session auth; that path was removed when the server
    # moved to the multi-user SSO model (no per-user password). See
    # docs/adr/0001-multi-user-auth-via-oidc-token-exchange.md.

    @mcp.tool()
    async def log_ingredient(
        plan_id: str,
        ingredient_id: str,
        amount_g: Annotated[float, Field(gt=0, le=10000)],
        when: date | datetime | None = None,
        meal_id: str | None = None,
    ) -> dict[str, Any]:
        """Log eaten food against a plan (logitem).

        ``when`` accepts either a full timestamp or a bare date:

        - ``"2026-07-21T07:30:00+02:00"`` — logged at exactly that instant, the
          offset preserved. Use this to record when a meal was actually eaten.
        - ``"2026-07-21"`` — a date with no time, anchored at 12:00 local.
        - omitted — wger timestamps the entry with the current time.

        ``meal_id`` optionally attributes the entry to a specific meal of the
        plan; omit it for a standalone diary entry.
        """
        payload: dict[str, Any] = {
            "plan": plan_id,
            "ingredient": ingredient_id,
            "amount": amount_g,
        }
        # Only send 'datetime' when the caller asked for a specific time —
        # otherwise let wger apply its own default rather than pinning the
        # entry to an arbitrary hour.
        stamp = _diary_timestamp(when)
        if stamp is not None:
            payload["datetime"] = stamp
        if meal_id is not None:
            payload["meal"] = meal_id
        try:
            return await client.post("nutritiondiary/", json=payload)
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def update_log_item(
        log_item_id: str,
        amount_g: Annotated[float | None, Field(gt=0, le=10000)] = None,
        when: date | datetime | None = None,
        ingredient_id: str | None = None,
        meal_id: str | None = None,
    ) -> dict[str, Any]:
        """Patch an existing nutrition-diary entry.

        Use this to correct an entry's time or amount in place. ``when`` takes
        the same forms as in ``log_ingredient``; only the fields you pass are
        changed.
        """
        payload: dict[str, Any] = {}
        if amount_g is not None:
            payload["amount"] = amount_g
        stamp = _diary_timestamp(when)
        if stamp is not None:
            payload["datetime"] = stamp
        if ingredient_id is not None:
            payload["ingredient"] = ingredient_id
        if meal_id is not None:
            payload["meal"] = meal_id
        if not payload:
            return bad_request("no fields to update")
        try:
            return await client.patch(f"nutritiondiary/{log_item_id}/", json=payload)
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def list_log_items(
        when: date | None = None,
        plan_id: str | None = None,
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
    async def delete_log_item(log_item_id: str) -> dict[str, Any]:
        """Delete a nutrition-diary log item (a logged ingredient entry)."""
        try:
            await client.delete(f"nutritiondiary/{log_item_id}/")
            return {"deleted": True, "log_item_id": log_item_id}
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def calculate_daily_calories(
        weight_kg: Annotated[float | None, Field(gt=20, le=400)] = None,
        height_cm: Annotated[float | None, Field(gt=80, le=260)] = None,
        age: Annotated[int | None, Field(ge=10, le=100)] = None,
        sex: Annotated[str | None, Field(pattern=r"^(male|female)$")] = None,
        activity_level: str = "moderate",
        goal: str = "maintain",
        protein_g_per_kg: Annotated[float, Field(ge=0.8, le=3.5)] = 1.8,
        fat_pct_of_kcal: Annotated[float, Field(ge=15, le=45)] = 25.0,
        apply_to_profile: bool = False,
    ) -> dict[str, Any]:
        """Compute daily kcal target and macro split.

        Uses the Mifflin-St Jeor BMR formula x activity multiplier x goal
        adjustment. Macro split: protein from g/kg bodyweight, fat from % of
        target kcal, carbs from the remainder.

        Any of weight_kg / height_cm / age / sex left as None are auto-filled:
        height/age/sex from /userprofile/ (gender "1"=male, "2"=female),
        weight from the latest /weightentry/. If apply_to_profile=True, PATCH
        the resulting target_kcal into userprofile.calories.

        activity_level: sedentary (1.2), light (1.375), moderate (1.55),
        active (1.725), very_active (1.9).
        goal: cut (-500 kcal), maintain (0), bulk (+300 kcal).
        """
        activity_multipliers = {
            "sedentary": 1.2,
            "light": 1.375,
            "moderate": 1.55,
            "active": 1.725,
            "very_active": 1.9,
        }
        goal_deltas = {"cut": -500.0, "maintain": 0.0, "bulk": 300.0}
        if activity_level not in activity_multipliers:
            return bad_request(
                f"activity_level must be one of {sorted(activity_multipliers)}"
            )
        if goal not in goal_deltas:
            return bad_request(f"goal must be one of {sorted(goal_deltas)}")

        source: dict[str, str] = {}
        for key, val in (
            ("weight_kg", weight_kg),
            ("height_cm", height_cm),
            ("age", age),
            ("sex", sex),
        ):
            if val is not None:
                source[key] = "argument"

        need_profile = any(v is None for v in (height_cm, age, sex))
        need_weight = weight_kg is None
        if need_profile or need_weight:
            profile_coro = client.get("userprofile/") if need_profile else None
            weight_coro = (
                client.paginate("weightentry/", params={"ordering": "-date"}, limit=1)
                if need_weight
                else None
            )
            coros = [c for c in (profile_coro, weight_coro) if c is not None]
            try:
                results = await asyncio.gather(*coros)
            except WgerError as exc:
                return err(exc)
            idx = 0
            profile = results[idx] if need_profile else None
            if need_profile:
                idx += 1
            latest_weights = results[idx] if need_weight else None

            if isinstance(profile, dict):
                if height_cm is None and profile.get("height") is not None:
                    try:
                        height_cm = float(profile["height"])
                        source["height_cm"] = "userprofile"
                    except (TypeError, ValueError):
                        pass
                if age is None and profile.get("age") is not None:
                    try:
                        age = int(profile["age"])
                        source["age"] = "userprofile"
                    except (TypeError, ValueError):
                        pass
                if sex is None:
                    gender = str(profile.get("gender") or "")
                    if gender == "1":
                        sex = "male"
                        source["sex"] = "userprofile"
                    elif gender == "2":
                        sex = "female"
                        source["sex"] = "userprofile"
            if weight_kg is None and latest_weights:
                latest = latest_weights[0] if isinstance(latest_weights, list) else None
                if isinstance(latest, dict):
                    try:
                        weight_kg = float(latest.get("weight") or 0) or None
                        if weight_kg is not None:
                            source["weight_kg"] = "weightentry"
                    except (TypeError, ValueError):
                        pass

        missing = [
            name
            for name, val in (
                ("weight_kg", weight_kg),
                ("height_cm", height_cm),
                ("age", age),
                ("sex", sex),
            )
            if val is None
        ]
        if missing:
            return bad_request(
                "missing required fields (not found in wger profile / weight history): "
                + ", ".join(missing)
            )

        # Mifflin-St Jeor
        base = 10 * weight_kg + 6.25 * height_cm - 5 * age
        bmr = base + (5 if sex == "male" else -161)
        tdee = bmr * activity_multipliers[activity_level]
        target = tdee + goal_deltas[goal]

        protein_g = protein_g_per_kg * weight_kg
        fat_g = (fat_pct_of_kcal / 100.0) * target / 9.0
        carbs_kcal = target - (protein_g * 4 + fat_g * 9)
        carbs_g = max(carbs_kcal / 4.0, 0.0)

        target_kcal = round(target, 0)
        result: dict[str, Any] = {
            "bmr_kcal": round(bmr, 0),
            "tdee_kcal": round(tdee, 0),
            "target_kcal": target_kcal,
            "macros": {
                "protein_g": round(protein_g, 1),
                "fat_g": round(fat_g, 1),
                "carbs_g": round(carbs_g, 1),
            },
            "inputs": {
                "weight_kg": weight_kg,
                "height_cm": height_cm,
                "age": age,
                "sex": sex,
                "activity_level": activity_level,
                "goal": goal,
                "protein_g_per_kg": protein_g_per_kg,
                "fat_pct_of_kcal": fat_pct_of_kcal,
            },
            "input_sources": source,
            "formula": "Mifflin-St Jeor",
        }

        if apply_to_profile:
            try:
                patched = await client.patch(
                    "userprofile/", json={"calories": int(target_kcal)}
                )
                result["profile_update"] = {
                    "applied": True,
                    "calories": (
                        patched.get("calories") if isinstance(patched, dict) else None
                    ),
                }
            except WgerError as exc:
                result["profile_update"] = {"applied": False, "error": err(exc)}

        return result

    @mcp.tool()
    async def update_user_profile(
        calories: Annotated[int | None, Field(ge=800, le=10000)] = None,
        height_cm: Annotated[int | None, Field(gt=80, le=260)] = None,
        birthdate: date | None = None,
        gender: Annotated[str | None, Field(pattern=r"^(1|2)$")] = None,
        sleep_hours: Annotated[int | None, Field(ge=0, le=24)] = None,
        work_hours: Annotated[int | None, Field(ge=0, le=24)] = None,
        work_intensity: Annotated[str | None, Field(pattern=r"^[123]$")] = None,
        sport_hours: Annotated[int | None, Field(ge=0, le=24)] = None,
        sport_intensity: Annotated[str | None, Field(pattern=r"^[123]$")] = None,
        freetime_hours: Annotated[int | None, Field(ge=0, le=24)] = None,
        freetime_intensity: Annotated[str | None, Field(pattern=r"^[123]$")] = None,
    ) -> dict[str, Any]:
        """Patch the wger user profile. gender: '1'=male, '2'=female.
        intensity fields: '1'=low, '2'=moderate, '3'=high."""
        payload: dict[str, Any] = {}
        if calories is not None:
            payload["calories"] = calories
        if height_cm is not None:
            payload["height"] = height_cm
        if birthdate is not None:
            payload["birthdate"] = birthdate.isoformat()
        if gender is not None:
            payload["gender"] = gender
        if sleep_hours is not None:
            payload["sleep_hours"] = sleep_hours
        if work_hours is not None:
            payload["work_hours"] = work_hours
        if work_intensity is not None:
            payload["work_intensity"] = work_intensity
        if sport_hours is not None:
            payload["sport_hours"] = sport_hours
        if sport_intensity is not None:
            payload["sport_intensity"] = sport_intensity
        if freetime_hours is not None:
            payload["freetime_hours"] = freetime_hours
        if freetime_intensity is not None:
            payload["freetime_intensity"] = freetime_intensity
        if not payload:
            return bad_request("no fields to update")
        try:
            return await client.patch("userprofile/", json=payload)
        except WgerError as exc:
            return err(exc)

    @mcp.tool()
    async def nutrition_summary(
        when: date | None = None,
        plan_id: str | None = None,
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

        # Fan out distinct ingredient fetches concurrently.
        ing_ids: set[int] = set()
        for entry in entries:
            ing_id = entry.get("ingredient")
            if ing_id and float(entry.get("amount") or 0) > 0:
                ing_ids.add(ing_id)

        sem = asyncio.Semaphore(_INGREDIENT_CONCURRENCY)

        async def _fetch(iid: int) -> tuple[int, dict[str, Any]]:
            async with sem:
                try:
                    return iid, await client.get(f"ingredient/{iid}/")
                except WgerError as exc:
                    return iid, {"_err": err(exc)}

        cache: dict[int, dict[str, Any]] = dict(
            await asyncio.gather(*[_fetch(i) for i in ing_ids])
        )

        totals = {"kcal": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
        items: list[dict[str, Any]] = []
        for entry in entries:
            ing_id = entry.get("ingredient")
            amount = float(entry.get("amount") or 0)
            if not ing_id or amount <= 0:
                continue
            ing = cache.get(ing_id) or {}
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
