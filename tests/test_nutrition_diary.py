"""Nutrition-diary timestamps: issue #5 — custom datetimes on log entries."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
import respx
from mcp.server.fastmcp import FastMCP

from wger_mcp.config import Settings
from wger_mcp.tools import nutrition
from wger_mcp.wger_client import WgerClient

API = "https://wger.test/api/v2"


class _StubProvider:
    async def authorization_header(self) -> str:
        return "Token dev"

    async def aclose(self) -> None:
        pass


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        wger_base_url="https://wger.test",
        mcp_auth="none",
        wger_dev_token="dev",
    )


def _register() -> tuple[FastMCP, WgerClient]:
    mcp = FastMCP("test")
    client = WgerClient(API, _StubProvider())
    nutrition.register(mcp, client, _settings())
    return mcp, client


def _sent(route: Any) -> dict[str, Any]:
    return json.loads(route.calls.last.request.content)


# ---------- _diary_timestamp ----------


def test_none_yields_no_timestamp() -> None:
    """Omitting the field lets wger apply its own timezone.now default."""
    assert nutrition._diary_timestamp(None) is None


def test_bare_date_is_anchored_at_noon() -> None:
    assert nutrition._diary_timestamp(date(2026, 7, 21)) == "2026-07-21T12:00:00"


def test_datetime_offset_is_preserved() -> None:
    """The reporter's case: an explicit offset must survive verbatim."""
    tz = timezone(timedelta(hours=2))
    stamp = nutrition._diary_timestamp(datetime(2026, 7, 21, 7, 0, tzinfo=tz))
    assert stamp == "2026-07-21T07:00:00+02:00"


def test_naive_datetime_keeps_its_time() -> None:
    assert nutrition._diary_timestamp(datetime(2026, 7, 21, 7, 30)) == "2026-07-21T07:30:00"


def test_datetime_checked_before_date() -> None:
    """datetime subclasses date, so a naive isinstance order would truncate."""
    assert nutrition._diary_timestamp(datetime(2026, 7, 21, 23, 45)) != "2026-07-21T12:00:00"


# ---------- log_ingredient ----------


@pytest.mark.asyncio
async def test_log_ingredient_forwards_iso_datetime() -> None:
    """Regression for issue #5: an ISO 8601 date-time reaches wger intact.

    Previously every entry was pinned to a hard-coded 12:00Z regardless of
    what the caller passed.
    """
    mcp, client = _register()
    async with client:
        with respx.mock(base_url=API) as router:
            route = router.post("/nutritiondiary/").respond(json={"id": 1})
            await mcp.call_tool(
                "log_ingredient",
                {
                    "plan_id": "plan-uuid",
                    "ingredient_id": "1677954",
                    "amount_g": 100,
                    "when": "2026-07-21T07:00:00+02:00",
                },
            )
    assert _sent(route)["datetime"] == "2026-07-21T07:00:00+02:00"


@pytest.mark.asyncio
async def test_log_ingredient_omits_datetime_when_unset() -> None:
    """No 'when' must send no 'datetime', so wger stamps it itself."""
    mcp, client = _register()
    async with client:
        with respx.mock(base_url=API) as router:
            route = router.post("/nutritiondiary/").respond(json={"id": 1})
            await mcp.call_tool(
                "log_ingredient",
                {"plan_id": "plan-uuid", "ingredient_id": "1", "amount_g": 50},
            )
    body = _sent(route)
    assert "datetime" not in body
    assert body == {"plan": "plan-uuid", "ingredient": "1", "amount": 50.0}


@pytest.mark.asyncio
async def test_log_ingredient_accepts_bare_date() -> None:
    mcp, client = _register()
    async with client:
        with respx.mock(base_url=API) as router:
            route = router.post("/nutritiondiary/").respond(json={"id": 1})
            await mcp.call_tool(
                "log_ingredient",
                {
                    "plan_id": "p",
                    "ingredient_id": "1",
                    "amount_g": 10,
                    "when": "2026-07-21",
                },
            )
    assert _sent(route)["datetime"] == "2026-07-21T12:00:00"


@pytest.mark.asyncio
async def test_log_ingredient_optional_meal() -> None:
    mcp, client = _register()
    async with client:
        with respx.mock(base_url=API) as router:
            route = router.post("/nutritiondiary/").respond(json={"id": 1})
            await mcp.call_tool(
                "log_ingredient",
                {"plan_id": "p", "ingredient_id": "1", "amount_g": 10, "meal_id": "m1"},
            )
    assert _sent(route)["meal"] == "m1"


# ---------- update_log_item ----------


@pytest.mark.asyncio
async def test_update_log_item_patches_time() -> None:
    """Correcting an entry's time in place — wger's web UI cannot do this."""
    mcp, client = _register()
    async with client:
        with respx.mock(base_url=API) as router:
            route = router.patch("/nutritiondiary/42/").respond(json={"id": 42})
            await mcp.call_tool(
                "update_log_item",
                {"log_item_id": "42", "when": "2026-07-21T19:15:00+02:00"},
            )
    assert _sent(route) == {"datetime": "2026-07-21T19:15:00+02:00"}


@pytest.mark.asyncio
async def test_update_log_item_sends_only_given_fields() -> None:
    mcp, client = _register()
    async with client:
        with respx.mock(base_url=API) as router:
            route = router.patch("/nutritiondiary/7/").respond(json={"id": 7})
            await mcp.call_tool("update_log_item", {"log_item_id": "7", "amount_g": 250})
    assert _sent(route) == {"amount": 250.0}


@pytest.mark.asyncio
async def test_update_log_item_rejects_empty_patch() -> None:
    mcp, client = _register()
    async with client:
        # assert_all_called=False: the point of this test is that the route is
        # never reached.
        with respx.mock(base_url=API, assert_all_called=False) as router:
            route = router.patch("/nutritiondiary/7/").respond(json={})
            result = await mcp.call_tool("update_log_item", {"log_item_id": "7"})
    assert route.call_count == 0
    assert "no fields to update" in str(result)
