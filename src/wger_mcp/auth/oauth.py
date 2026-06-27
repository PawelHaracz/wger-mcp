"""OAuth 2.0 Protected Resource Metadata (RFC 9728) for MCP-native auth.

Interactive MCP clients (e.g. Claude) discover where to authenticate by
fetching ``/.well-known/oauth-protected-resource``. We point them at our SSO
IdP as the authorization server; the client runs the OAuth flow with the IdP
and presents the resulting token to this server.
"""

from __future__ import annotations

from starlette.requests import Request

from ..config import Settings

WELL_KNOWN_PATH = "/.well-known/oauth-protected-resource"


def forwarded_origin(request: Request) -> str | None:
    """Public ``scheme://host`` origin inferred from reverse-proxy headers.

    Honours ``X-Forwarded-Proto`` / ``X-Forwarded-Host`` (first value of each,
    as a proxy chain may append several), falling back to the request's own
    scheme and ``Host`` header. Returns ``None`` when no host can be determined.
    """

    def _first(value: str | None) -> str | None:
        return value.split(",")[0].strip() if value else None

    proto = _first(request.headers.get("x-forwarded-proto")) or request.url.scheme
    host = _first(request.headers.get("x-forwarded-host")) or request.headers.get("host")
    if not host:
        return None
    return f"{proto}://{host}"


def resource_identifier(settings: Settings, *, origin: str | None = None) -> str:
    """The canonical public URL clients use to reach this MCP server.

    Resolution order:

    1. ``MCP_PUBLIC_URL`` — explicit config, always wins.
    2. ``origin`` — derived from the request's reverse-proxy forwarded headers,
       so a deploy behind nginx needs no per-host config.
    3. ``host:port`` — dev fallback; yields ``0.0.0.0`` when bound to all
       interfaces, which is only useful for local testing.
    """
    if settings.mcp_public_url:
        return str(settings.mcp_public_url).rstrip("/")
    if origin:
        return origin.rstrip("/")
    return f"http://{settings.host}:{settings.port}".rstrip("/")


def resource_metadata_url(settings: Settings, *, origin: str | None = None) -> str:
    return resource_identifier(settings, origin=origin) + WELL_KNOWN_PATH


def protected_resource_metadata(settings: Settings, *, origin: str | None = None) -> dict:
    # This server fronts the IdP as an OAuth AS facade (see auth/asfacade.py), so
    # it advertises *itself* as the authorization server. Clients then fetch our
    # /.well-known/oauth-authorization-server and drive the flow against this
    # origin — the private IdP never needs to be reachable by the client.
    base = resource_identifier(settings, origin=origin)
    return {
        "resource": base,
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
    }
