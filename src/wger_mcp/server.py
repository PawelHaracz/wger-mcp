"""FastMCP server: wger tools exposed over streamable HTTP with pluggable auth.

Tool implementations live in ``wger_mcp.tools``; this module only wires the
FastMCP instance, the upstream HTTP client, the Starlette app, and lifespan.
"""

from __future__ import annotations

import contextlib
import logging

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .auth import build_auth_middleware
from .config import Settings, load_settings
from .tools import register_all
from .wger_client import WgerClient
from .wger_session import WgerSession

log = logging.getLogger("wger_mcp")


def build_app(settings: Settings) -> Starlette:
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=bool(settings.allowed_hosts),
        allowed_hosts=settings.allowed_hosts,
    )
    mcp = FastMCP(
        "wger",
        json_response=True,
        streamable_http_path=settings.mcp_path,
        transport_security=transport_security,
    )

    client = WgerClient(settings.wger_api_root, settings.wger_api_token)
    if settings.wger_username and settings.wger_password:
        client.session = WgerSession(
            str(settings.wger_base_url).rstrip("/"),
            settings.wger_username,
            settings.wger_password,
            lang=settings.wger_web_lang,
        )
    register_all(mcp, client)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        async with mcp.session_manager.run():
            try:
                yield
            finally:
                await client.aclose()

    async def healthcheck(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    # streamable_http_app() registers Route(mcp_path, ...) internally.
    # Merging its routes into the top-level Starlette avoids the double-prefix
    # problem: an outer Mount("/mcp/") would strip the prefix before routing,
    # leaving "" which never matches the inner Route("/mcp/") → 404.
    # For every MCP route we also register its slash-twin (the same path with the
    # trailing "/" toggled) so `/mcp` and `/mcp/` both hit the ASGI app no matter
    # how MCP_PATH is written. MCP clients (and curl) do not follow the 307
    # redirect_slashes would otherwise emit on POST, so a twin is required rather
    # than a redirect.
    mcp_starlette = mcp.streamable_http_app()
    mcp_routes: list[Route] = []
    seen_paths: set[str] = set()
    for route in mcp_starlette.routes:
        mcp_routes.append(route)
        path = getattr(route, "path", None)
        if path:
            seen_paths.add(path)
    for route in list(mcp_routes):
        path = getattr(route, "path", None)
        endpoint = getattr(route, "endpoint", None) or getattr(route, "app", None)
        if not path or not endpoint:
            continue
        twin = path[:-1] if path.endswith("/") else path + "/"
        if twin and twin not in seen_paths:
            mcp_routes.append(Route(twin, endpoint))
            seen_paths.add(twin)
    routes = [Route("/health", healthcheck), *mcp_routes]
    app = Starlette(routes=routes, lifespan=lifespan)
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
