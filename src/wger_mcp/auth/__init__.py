"""Auth for incoming MCP requests and the outbound wger credential.

Inbound (``MCP_AUTH``):

- ``oidc`` — validate an SSO (OIDC) token; carry it for token-exchange.
- ``none`` — local-dev only; no inbound auth, static dev token outbound.

Outbound is always a per-request wger credential supplied by a
:class:`WgerTokenProvider` (see ``exchange.py`` and ``docs/adr/0001``).
"""

from __future__ import annotations

from typing import Any

from ..config import AuthStrategy, Settings
from .base import NoAuthMiddleware
from .exchange import TokenExchanger, WgerTokenProvider
from .oauth import (
    WELL_KNOWN_PATH,
    protected_resource_metadata,
    resource_metadata_url,
)
from .oidc import OidcAuthMiddleware
from .oidc_discovery import discover_endpoints

__all__ = [
    "WELL_KNOWN_PATH",
    "NoAuthMiddleware",
    "OidcAuthMiddleware",
    "TokenExchanger",
    "WgerTokenProvider",
    "build_auth_middleware",
    "build_token_provider",
    "protected_resource_metadata",
    "resource_metadata_url",
]


def _resolve_endpoints(s: Settings) -> tuple[str, str]:
    return discover_endpoints(
        str(s.oidc_issuer),
        jwks_uri=str(s.oidc_jwks_uri) if s.oidc_jwks_uri else None,
        token_endpoint=str(s.oidc_token_endpoint) if s.oidc_token_endpoint else None,
    )


def build_auth_middleware(settings: Settings) -> tuple[type, dict[str, Any]]:
    """Pick an inbound auth middleware class + kwargs based on settings."""
    s = settings
    match s.mcp_auth:
        case AuthStrategy.none:
            return NoAuthMiddleware, {}
        case AuthStrategy.oidc:
            jwks_uri, _ = _resolve_endpoints(s)
            return OidcAuthMiddleware, {
                "jwks_uri": jwks_uri,
                "issuer": str(s.oidc_issuer),
                "audience": s.mcp_oidc_audience,
                "algorithms": s.mcp_oidc_algorithms,
                "username_claim": s.mcp_oidc_username_claim,
                "allowed_users": set(s.mcp_oidc_allowed_users),
                "jwks_ttl_seconds": s.mcp_jwks_ttl_seconds,
                "resource_metadata_url": resource_metadata_url(s),
            }
    raise RuntimeError(f"unsupported MCP_AUTH: {s.mcp_auth}")  # pragma: no cover


def build_token_provider(settings: Settings) -> WgerTokenProvider:
    """Build the outbound wger credential provider for the chosen strategy."""
    s = settings
    if s.mcp_auth is AuthStrategy.none:
        return WgerTokenProvider(dev_token=s.wger_dev_token)
    _, token_endpoint = _resolve_endpoints(s)
    exchanger = TokenExchanger(
        token_endpoint=token_endpoint,
        client_id=str(s.oidc_client_id),
        client_secret=str(s.oidc_client_secret),
        wger_audience=str(s.wger_oidc_audience),
        provider_token_url=s.provider_token_url,
        provider=s.wger_allauth_provider,
    )
    return WgerTokenProvider(exchanger=exchanger)
