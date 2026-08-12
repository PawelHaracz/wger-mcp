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

from .auth import (
    AS_METADATA_PATH,
    WELL_KNOWN_PATH,
    build_auth_middleware,
    build_authorization_server_facade,
    build_token_provider,
    forwarded_origin,
    protected_resource_metadata,
    resource_identifier,
)
from .config import AuthStrategy, Settings, load_settings
from .tools import register_all
from .wger_client import WgerClient

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

    client = WgerClient(settings.wger_api_root, build_token_provider(settings))
    register_all(mcp, client, settings)

    # AS facade: lets a client that treats this origin as the OAuth authorization
    # server (e.g. claude.ai) reach a private IdP. None when not in OIDC mode.
    as_facade = build_authorization_server_facade(settings)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        async with mcp.session_manager.run():
            try:
                yield
            finally:
                await client.aclose()
                if as_facade is not None:
                    await as_facade.aclose()

    async def healthcheck(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    async def oauth_metadata(request: Request) -> JSONResponse:
        origin = forwarded_origin(request)
        return JSONResponse(protected_resource_metadata(settings, origin=origin))

    async def as_metadata(request: Request) -> JSONResponse:
        origin = resource_identifier(settings, origin=forwarded_origin(request))
        return JSONResponse(as_facade.metadata(origin))

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
    # OAuth-protected-resource metadata lets interactive MCP clients discover
    # the SSO IdP as the authorization server. Only meaningful when OIDC is the
    # inbound strategy: advertising it under static_token/none would send
    # clients through an OAuth flow whose result the server never accepts.
    if settings.mcp_auth is AuthStrategy.oidc and settings.oidc_issuer is not None:
        routes.append(Route(WELL_KNOWN_PATH, oauth_metadata))
        if as_facade is not None:
            routes.append(Route(AS_METADATA_PATH, as_metadata))
            routes.append(
                Route(settings.oauth_authorize_path, as_facade.authorize, methods=["GET"])
            )
            routes.append(
                Route(settings.oauth_token_path, as_facade.token, methods=["POST"])
            )
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
