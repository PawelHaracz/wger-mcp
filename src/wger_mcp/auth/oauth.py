"""OAuth 2.0 Protected Resource Metadata (RFC 9728) for MCP-native auth.

Interactive MCP clients (e.g. Claude) discover where to authenticate by
fetching ``/.well-known/oauth-protected-resource``. We point them at our SSO
IdP as the authorization server; the client runs the OAuth flow with the IdP
and presents the resulting token to this server.
"""

from __future__ import annotations

from ..config import Settings

WELL_KNOWN_PATH = "/.well-known/oauth-protected-resource"


def resource_identifier(settings: Settings) -> str:
    """The canonical public URL clients use to reach this MCP server."""
    if settings.mcp_public_url:
        return str(settings.mcp_public_url).rstrip("/")
    return f"http://{settings.host}:{settings.port}".rstrip("/")


def resource_metadata_url(settings: Settings) -> str:
    return resource_identifier(settings) + WELL_KNOWN_PATH


def protected_resource_metadata(settings: Settings) -> dict:
    return {
        "resource": resource_identifier(settings),
        "authorization_servers": [str(settings.oidc_issuer).rstrip("/")],
        "bearer_methods_supported": ["header"],
    }
