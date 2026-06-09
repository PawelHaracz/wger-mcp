"""Open Food Facts lookup tools.

OFF is a free, community-maintained food database (~3.6 M products) with rich
Polish coverage. Use these tools when you have an EAN/UPC barcode and want
macros — much more precise than name search. Output includes a
`wger_ingredient_payload` field that can be fed straight into the wger
``create_ingredient`` tool.
"""

from __future__ import annotations

from typing import Annotated, Any

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..wger_client import WgerClient

_OFF_BASE_URL = "https://world.openfoodfacts.org"
_OFF_TIMEOUT = 15.0
_BATCH_CONCURRENCY = 4  # OFF burst-limits aggressively; keep modest
_RETRY_429_DELAY = 2.0  # seconds before single retry on rate-limit
_FIELDS = ",".join([
    "code",
    "product_name",
    "product_name_pl",
    "brands",
    "quantity",
    "countries_tags",
    "ingredients_text_pl",
    "nutriscore_grade",
    "nova_group",
    "nutriments",
])


def _f(nut: dict[str, Any], *keys: str) -> float | None:
    """First non-null float value across the given OFF nutriment keys."""
    for k in keys:
        v = nut.get(k)
        if v is None or v == "":
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _shape(prod: dict[str, Any]) -> dict[str, Any]:
    """Flatten an OFF product into a wger-aware structure."""
    nut = prod.get("nutriments") or {}

    energy = _f(nut, "energy-kcal_100g", "energy-kcal")
    protein = _f(nut, "proteins_100g")
    carbs = _f(nut, "carbohydrates_100g")
    sugars = _f(nut, "sugars_100g")
    fat = _f(nut, "fat_100g")
    fat_sat = _f(nut, "saturated-fat_100g")
    fiber = _f(nut, "fiber_100g")
    salt = _f(nut, "salt_100g")
    sodium = _f(nut, "sodium_100g")
    # OFF stores salt; wger stores sodium. Convert if sodium is missing.
    if sodium is None and salt is not None:
        sodium = round(salt / 2.5, 4)

    name = prod.get("product_name_pl") or prod.get("product_name") or None
    if isinstance(name, list):
        name = name[0] if name else None
    brand = prod.get("brands") or None
    if isinstance(brand, list):
        brand = brand[0] if brand else None

    macros_per_100g = {
        "energy_kcal": energy,
        "protein_g": protein,
        "carbohydrates_g": carbs,
        "carbohydrates_sugar_g": sugars,
        "fat_g": fat,
        "fat_saturated_g": fat_sat,
        "fiber_g": fiber,
        "salt_g": salt,
        "sodium_g": sodium,
    }

    # A payload that maps onto create_ingredient's keyword arguments. The
    # caller can splat this dict directly into create_ingredient(**payload).
    wger_payload: dict[str, Any] = {
        "name": name,
        "brand": brand or "",
        "code": prod.get("code"),
    }
    if energy is not None:
        wger_payload["energy_kcal"] = energy
    if protein is not None:
        wger_payload["protein_g"] = protein
    if carbs is not None:
        wger_payload["carbohydrates_g"] = carbs
    if fat is not None:
        wger_payload["fat_g"] = fat
    if sugars is not None:
        wger_payload["carbohydrates_sugar_g"] = sugars
    if fat_sat is not None:
        wger_payload["fat_saturated_g"] = fat_sat
    if fiber is not None:
        wger_payload["fiber_g"] = fiber
    if sodium is not None:
        wger_payload["sodium_g"] = sodium

    return {
        "found": True,
        "code": prod.get("code"),
        "name": name,
        "name_pl": prod.get("product_name_pl") or None,
        "name_default": prod.get("product_name") or None,
        "brand": brand,
        "quantity": prod.get("quantity"),
        "countries": prod.get("countries_tags"),
        "ingredients_text_pl": prod.get("ingredients_text_pl") or None,
        "nutriscore_grade": prod.get("nutriscore_grade"),
        "nova_group": prod.get("nova_group"),
        "macros_per_100g": macros_per_100g,
        "wger_ingredient_payload": wger_payload,
        "source": "openfoodfacts.org",
    }


def register(mcp: FastMCP, client: WgerClient) -> None:
    # One httpx client for OFF, lifetime-bound to the wger client via the
    # _extra_clients hook (closed in WgerClient.aclose).
    http = httpx.AsyncClient(
        base_url=_OFF_BASE_URL,
        timeout=_OFF_TIMEOUT,
        headers={"User-Agent": "wger-mcp/0.1 (+OFF-lookup)"},
    )
    extras = getattr(client, "_extra_clients", None)
    if extras is None:
        extras = []
        client._extra_clients = extras  # type: ignore[attr-defined]
    extras.append(http)

    @mcp.tool()
    async def lookup_food_by_barcode(
        barcode: Annotated[str, Field(min_length=4, max_length=32)],
    ) -> dict[str, Any]:
        """Look up an EAN/UPC/GTIN barcode on Open Food Facts.

        Returns macros per 100 g plus a ``wger_ingredient_payload`` ready to
        pass to ``create_ingredient`` (kwarg names match). Polish product name
        and ingredients text are preferred when present.

        Salt vs sodium: OFF stores salt only; if sodium is missing we derive
        ``sodium = salt / 2.5`` (the standard conversion).

        Not found → response includes a ``suggestion`` URL where you can add
        the product to OFF. After acceptance there it'll sync into your wger
        instance on the next ingredient-sync run.
        """
        try:
            resp = await http.get(f"/api/v2/product/{barcode}.json", params={"fields": _FIELDS})
        except httpx.HTTPError as exc:
            return {"error": True, "status": 503, "detail": f"OFF unreachable: {exc}"}
        if resp.status_code >= 400:
            return {"error": True, "status": resp.status_code, "detail": resp.text[:200]}
        try:
            data = resp.json()
        except ValueError:
            return {"error": True, "status": 502, "detail": "non-JSON response from OFF"}
        if data.get("status") != 1:
            return {
                "found": False,
                "code": barcode,
                "detail": data.get("status_verbose") or "product not found",
                "suggestion": (
                    "Not in Open Food Facts. You can add it at "
                    f"https://world.openfoodfacts.org/cgi/product.pl?type=add&code={barcode} "
                    "— community-moderated, free. After acceptance it syncs into wger."
                ),
            }
        return _shape(data["product"])

    async def _fetch_one(code: str) -> dict[str, Any]:
        """One barcode fetch with a single retry on 429 (rate limit)."""
        for attempt in (1, 2):
            try:
                resp = await http.get(
                    f"/api/v2/product/{code}.json", params={"fields": _FIELDS}
                )
            except httpx.HTTPError as exc:
                return {"error": True, "status": 503, "detail": str(exc)}
            if resp.status_code == 429 and attempt == 1:
                # Respect server's Retry-After if present, else our default.
                try:
                    delay = float(resp.headers.get("retry-after") or _RETRY_429_DELAY)
                except ValueError:
                    delay = _RETRY_429_DELAY
                import asyncio as _asyncio

                await _asyncio.sleep(min(delay, 10.0))
                continue
            if resp.status_code >= 400:
                return {
                    "error": True,
                    "status": resp.status_code,
                    "detail": resp.text[:200],
                }
            try:
                data = resp.json()
            except ValueError:
                return {"error": True, "status": 502, "detail": "non-JSON"}
            if data.get("status") != 1:
                return {"found": False, "code": code}
            return _shape(data["product"])
        return {"error": True, "status": 429, "detail": "still rate-limited after retry"}

    @mcp.tool()
    async def lookup_foods_by_barcodes(
        barcodes: list[str],
    ) -> dict[str, Any]:
        """Batch variant: look up many EANs at once. Returns a map keyed by
        barcode. Fetches happen concurrently (capped at 4 in flight) with a
        one-shot retry on 429."""
        if not barcodes:
            return {"results": {}}
        import asyncio

        # Deduplicate while preserving order.
        unique = list(dict.fromkeys(barcodes))
        sem = asyncio.Semaphore(_BATCH_CONCURRENCY)

        async def _one(code: str) -> tuple[str, dict[str, Any]]:
            async with sem:
                return code, await _fetch_one(code)

        results = dict(await asyncio.gather(*[_one(c) for c in unique]))
        return {"count": len(results), "results": results}
