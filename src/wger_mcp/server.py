"""FastMCP server: wger tools exposed over streamable HTTP with pluggable auth."""

from __future__ import annotations

import contextlib
import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Annotated, Any

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .auth import build_auth_middleware
from .config import Settings, load_settings
from .wger_client import WgerClient, WgerError

log = logging.getLogger("wger_mcp")


def build_app(settings: Settings) -> Starlette:
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=bool(settings.allowed_hosts),
        allowed_hosts=settings.allowed_hosts,
    )
    mcp = FastMCP(
        "wger",
        json_response=True,
        streamable_http_path="/",
        transport_security=transport_security,
    )

    client = WgerClient(settings.wger_api_root, settings.wger_api_token)

    def _err(exc: WgerError) -> dict[str, Any]:
        return {"error": True, "status": exc.status, "detail": exc.body}

    @mcp.tool()
    async def whoami() -> dict[str, Any]:
        """Return the wger user profile bound to the configured API token."""
        try:
            return await client.get("userprofile/")
        except WgerError as exc:
            return _err(exc)

    @mcp.tool()
    async def list_routines(
        limit: Annotated[int, Field(ge=1, le=200)] = 20,
    ) -> list[dict[str, Any]]:
        """List the user's training routines (new wger model)."""
        try:
            return await client.paginate("routine/", limit=limit)
        except WgerError as exc:
            return [_err(exc)]

    @mcp.tool()
    async def get_routine(routine_id: int) -> dict[str, Any]:
        """Fetch a single routine with its day structure."""
        try:
            return await client.get(f"routine/{routine_id}/")
        except WgerError as exc:
            return _err(exc)

    @mcp.tool()
    async def create_routine(
        name: Annotated[str, Field(min_length=1, max_length=255)],
        description: str = "",
        start: date | None = None,
        end: date | None = None,
        fit_in_week: bool = False,
    ) -> dict[str, Any]:
        """Create a training routine. Start defaults to today."""
        payload: dict[str, Any] = {
            "name": name,
            "description": description,
            "start": (start or date.today()).isoformat(),
            "fit_in_week": fit_in_week,
        }
        if end is not None:
            payload["end"] = end.isoformat()
        try:
            return await client.post("routine/", json=payload)
        except WgerError as exc:
            return _err(exc)

    @mcp.tool()
    async def update_routine(
        routine_id: int,
        name: str | None = None,
        description: str | None = None,
        start: date | None = None,
        end: date | None = None,
        fit_in_week: bool | None = None,
    ) -> dict[str, Any]:
        """Patch a routine. Only provided fields are sent."""
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if description is not None:
            payload["description"] = description
        if start is not None:
            payload["start"] = start.isoformat()
        if end is not None:
            payload["end"] = end.isoformat()
        if fit_in_week is not None:
            payload["fit_in_week"] = fit_in_week
        if not payload:
            return {"error": True, "status": 400, "detail": "no fields to update"}
        try:
            return await client.patch(f"routine/{routine_id}/", json=payload)
        except WgerError as exc:
            return _err(exc)

    @mcp.tool()
    async def add_routine_day(
        routine_id: int,
        name: Annotated[str, Field(min_length=1, max_length=255)],
        order: Annotated[int, Field(ge=1, le=100)],
        description: str = "",
        is_rest: bool = False,
        day_type: str = "standard",
    ) -> dict[str, Any]:
        """Add a training day to a routine."""
        payload: dict[str, Any] = {
            "routine": routine_id,
            "order": order,
            "name": name,
            "description": description,
            "is_rest": is_rest,
            "type": day_type,
        }
        try:
            return await client.post("day/", json=payload)
        except WgerError as exc:
            return _err(exc)

    @mcp.tool()
    async def add_slot_to_day(
        day_id: int,
        order: Annotated[int, Field(ge=1, le=100)],
        sets: Annotated[int | None, Field(ge=1, le=50)] = None,
        rest_seconds: Annotated[int | None, Field(ge=0, le=3600)] = None,
    ) -> dict[str, Any]:
        """Add an exercise slot (grouping) to a day."""
        payload: dict[str, Any] = {"day": day_id, "order": order}
        if sets is not None:
            payload["sets"] = sets
        if rest_seconds is not None:
            payload["rest"] = rest_seconds
        try:
            return await client.post("slot/", json=payload)
        except WgerError as exc:
            return _err(exc)

    @mcp.tool()
    async def attach_exercise_to_slot(
        slot_id: int,
        exercise_id: int,
        order: Annotated[int, Field(ge=1, le=100)] = 1,
        repetition_unit: int | None = None,
        weight_unit: int | None = None,
        comment: str = "",
    ) -> dict[str, Any]:
        """Attach an exercise to a slot. exercise_id is the numeric wger PK
        (same id used in log_set / exerciseinfo). Per-set reps/weight live on
        sets-config / repetitions-config / weight-config records, not here."""
        payload: dict[str, Any] = {
            "slot": slot_id,
            "exercise": exercise_id,
            "order": order,
            "comment": comment,
        }
        if repetition_unit is not None:
            payload["repetition_unit"] = repetition_unit
        if weight_unit is not None:
            payload["weight_unit"] = weight_unit
        try:
            return await client.post("slot-entry/", json=payload)
        except WgerError as exc:
            return _err(exc)

    _SLOT_CONFIG_PATHS = {
        "sets": "sets-config/",
        "reps": "repetitions-config/",
        "weight": "weight-config/",
        "rir": "rir-config/",
        "rest": "rest-config/",
        "max_sets": "max-sets-config/",
        "max_reps": "max-repetitions-config/",
        "max_weight": "max-weight-config/",
        "max_rir": "max-rir-config/",
        "max_rest": "max-rest-config/",
    }

    @mcp.tool()
    async def set_slot_entry_config(
        slot_entry_id: int,
        kind: str,
        value: float,
        iteration: Annotated[int, Field(ge=1, le=1000)] = 1,
        operation: str = "r",
        step: str = "abs",
        repeat: bool = False,
    ) -> dict[str, Any]:
        """Create a per-iteration config record for a slot entry.
        kind: one of sets, reps, weight, rir, rest, max_sets, max_reps,
        max_weight, max_rir, max_rest. operation 'r' = replace, 'a' = add,
        's' = subtract. step 'abs' or 'percent'."""
        path = _SLOT_CONFIG_PATHS.get(kind)
        if not path:
            return {
                "error": True,
                "status": 400,
                "detail": f"unknown kind '{kind}'; expected one of {sorted(_SLOT_CONFIG_PATHS)}",
            }
        payload: dict[str, Any] = {
            "slot_entry": slot_entry_id,
            "iteration": iteration,
            "value": value,
            "operation": operation,
            "step": step,
            "repeat": repeat,
        }
        try:
            return await client.post(path, json=payload)
        except WgerError as exc:
            return _err(exc)

    @mcp.tool()
    async def add_exercise_with_sets(
        day_id: int,
        exercise_id: int,
        sets: Annotated[int, Field(ge=1, le=50)],
        reps: Annotated[int, Field(ge=1, le=1000)],
        weight_kg: Annotated[float, Field(ge=0, le=1000)],
        slot_order: Annotated[int, Field(ge=1, le=100)] = 1,
        rest_seconds: Annotated[int | None, Field(ge=0, le=3600)] = None,
    ) -> dict[str, Any]:
        """High-level convenience: create slot + slot-entry + sets/reps/weight
        configs in one call. Returns the created ids. Partial failures are
        reported in the response."""
        result: dict[str, Any] = {}
        slot_payload: dict[str, Any] = {"day": day_id, "order": slot_order}
        if rest_seconds is not None:
            slot_payload["rest"] = rest_seconds
        try:
            slot = await client.post("slot/", json=slot_payload)
        except WgerError as exc:
            return _err(exc) | {"stage": "slot"}
        result["slot"] = slot
        slot_id = slot.get("id") if isinstance(slot, dict) else None
        if not slot_id:
            return result | {"error": True, "stage": "slot", "detail": "missing slot id"}

        try:
            entry = await client.post(
                "slot-entry/",
                json={"slot": slot_id, "exercise": exercise_id, "order": 1, "comment": ""},
            )
        except WgerError as exc:
            return result | _err(exc) | {"stage": "slot-entry"}
        result["slot_entry"] = entry
        entry_id = entry.get("id") if isinstance(entry, dict) else None
        if not entry_id:
            return result | {"error": True, "stage": "slot-entry", "detail": "missing entry id"}

        for kind, value in (("sets", sets), ("reps", reps), ("weight", weight_kg)):
            try:
                result[f"{kind}_config"] = await client.post(
                    _SLOT_CONFIG_PATHS[kind],
                    json={
                        "slot_entry": entry_id,
                        "iteration": 1,
                        "value": value,
                        "operation": "r",
                        "step": "abs",
                        "repeat": False,
                    },
                )
            except WgerError as exc:
                return result | _err(exc) | {"stage": f"{kind}-config"}

        return result

    @mcp.tool()
    async def list_workouts(
        limit: Annotated[int, Field(ge=1, le=200)] = 20,
    ) -> list[dict[str, Any]]:
        """List legacy workout plans."""
        try:
            return await client.paginate("workout/", limit=limit)
        except WgerError as exc:
            return [_err(exc)]

    @mcp.tool()
    async def search_exercises(
        query: Annotated[str, Field(min_length=2)],
        language: Annotated[str, Field(pattern=r"^[a-z]{2}$")] = "en",
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
    ) -> list[dict[str, Any]]:
        """Search the wger exercise database by name. Language is ISO 639-1 ('en','pl',...)."""
        try:
            results = await client.paginate(
                "exerciseinfo/",
                params={"name__search": query, "language__code": language},
                limit=limit,
            )
        except WgerError as exc:
            return [_err(exc)]
        q_lower = query.lower()
        shaped: list[dict[str, Any]] = []
        for ex in results:
            if not isinstance(ex, dict):
                continue
            translations = [
                t for t in (ex.get("translations") or []) if isinstance(t, dict) and t.get("name")
            ]
            match = next(
                (t for t in translations if q_lower in (t.get("name") or "").lower()),
                translations[0] if translations else None,
            )
            shaped.append({
                "id": ex.get("id"),
                "uuid": ex.get("uuid"),
                "name": (match or {}).get("name"),
                "category": (ex.get("category") or {}).get("name"),
                "equipment": [e.get("name") for e in (ex.get("equipment") or [])],
                "translations": [
                    {"language": t.get("language"), "name": t.get("name")} for t in translations
                ],
            })
        return shaped

    @mcp.tool()
    async def log_set(
        exercise_id: int,
        reps: Annotated[int, Field(ge=1, le=1000)],
        weight_kg: Annotated[float, Field(ge=0, le=1000)],
        workout_log_date: date | None = None,
        rir: Annotated[float | None, Field(ge=0, le=10)] = None,
    ) -> dict[str, Any]:
        """Log a completed set (workoutlog). Uses today if no date given."""
        payload = {
            "exercise": exercise_id,
            "reps": reps,
            "weight": weight_kg,
            "date": (workout_log_date or date.today()).isoformat(),
        }
        if rir is not None:
            payload["rir"] = rir
        try:
            return await client.post("workoutlog/", json=payload)
        except WgerError as exc:
            return _err(exc)

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
            return _err(exc)

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
            return [_err(exc)]

    @mcp.tool()
    async def list_nutrition_plans(
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
    ) -> list[dict[str, Any]]:
        """List your nutrition plans."""
        try:
            return await client.paginate("nutritionplan/", limit=limit)
        except WgerError as exc:
            return [_err(exc)]

    @mcp.tool()
    async def get_nutrition_plan(plan_id: int) -> dict[str, Any]:
        """Fetch one nutrition plan with meals and items."""
        try:
            return await client.get(f"nutritionplan/{plan_id}/")
        except WgerError as exc:
            return _err(exc)

    @mcp.tool()
    async def get_exercise(exercise_id: int) -> dict[str, Any]:
        """Fetch full exercise detail (instructions, muscles, equipment)."""
        try:
            return await client.get(f"exerciseinfo/{exercise_id}/")
        except WgerError as exc:
            return _err(exc)

    @mcp.tool()
    async def search_ingredients(
        query: Annotated[str, Field(min_length=2)],
        language: Annotated[str, Field(pattern=r"^[a-z]{2}$")] = "en",
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
    ) -> list[dict[str, Any]]:
        """Search wger's ingredient database (foods with macros)."""
        try:
            results = await client.paginate(
                "ingredientinfo/",
                params={"name__search": query, "language__code": language},
                limit=limit,
            )
        except WgerError as exc:
            return [_err(exc)]
        shaped: list[dict[str, Any]] = []
        for ing in results:
            if not isinstance(ing, dict):
                continue
            shaped.append({
                "id": ing.get("id"),
                "uuid": ing.get("uuid"),
                "name": ing.get("name"),
                "energy": ing.get("energy"),
                "protein": ing.get("protein"),
                "carbohydrates": ing.get("carbohydrates"),
                "fat": ing.get("fat"),
                "brand": ing.get("brand"),
            })
        return shaped

    @mcp.tool()
    async def weekly_summary(
        days: Annotated[int, Field(ge=1, le=90)] = 7,
    ) -> dict[str, Any]:
        """Aggregate workoutlog over the last N days: sets/reps/volume per exercise."""
        since = (date.today() - timedelta(days=days - 1)).isoformat()
        try:
            logs = await client.paginate(
                "workoutlog/",
                params={"date__gte": since, "ordering": "date"},
                limit=1000,
            )
        except WgerError as exc:
            return _err(exc)

        per_exercise: dict[int, dict[str, Any]] = defaultdict(
            lambda: {"sets": 0, "reps": 0, "volume_kg": 0.0, "dates": set()}
        )
        for entry in logs:
            ex_id = entry.get("exercise") or entry.get("exercise_base")
            if ex_id is None:
                continue
            reps = entry.get("reps") or 0
            try:
                weight = float(entry.get("weight") or 0)
            except (TypeError, ValueError):
                weight = 0.0
            bucket = per_exercise[ex_id]
            bucket["sets"] += 1
            bucket["reps"] += reps
            bucket["volume_kg"] += reps * weight
            if d := entry.get("date"):
                bucket["dates"].add(d)

        breakdown = [
            {
                "exercise_id": ex_id,
                "sets": v["sets"],
                "reps": v["reps"],
                "volume_kg": round(v["volume_kg"], 2),
                "active_days": len(v["dates"]),
            }
            for ex_id, v in sorted(
                per_exercise.items(), key=lambda kv: kv[1]["volume_kg"], reverse=True
            )
        ]
        return {
            "since": since,
            "until": date.today().isoformat(),
            "total_sets": sum(v["sets"] for v in per_exercise.values()),
            "total_volume_kg": round(sum(v["volume_kg"] for v in per_exercise.values()), 2),
            "exercises": breakdown,
        }

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
            return _err(exc)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        async with mcp.session_manager.run():
            try:
                yield
            finally:
                await client.aclose()

    async def healthcheck(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    routes = [
        Route("/health", healthcheck),
        Mount(settings.mcp_path, app=mcp.streamable_http_app()),
    ]
    app = Starlette(routes=routes, lifespan=lifespan)
    # Keep `/mcp` and `/mcp/` both as MCP entry points instead of issuing a 307
    # from one to the other — MCP clients (and curl) do not follow redirects on POST.
    app.router.redirect_slashes = False
    auth_cls, auth_kwargs = build_auth_middleware(settings)
    app.add_middleware(auth_cls, **auth_kwargs)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = load_settings()
    log.info("MCP_AUTH=%s, MCP_PATH=%s", settings.mcp_auth.value, settings.mcp_path)
    app = build_app(settings)
    # forwarded_allow_ips="*" so uvicorn trusts X-Forwarded-Proto / -For from any
    # peer. Required when running behind a reverse proxy on a separate IP (the
    # default whitelist of 127.0.0.1 silently ignores headers from nginx etc).
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
