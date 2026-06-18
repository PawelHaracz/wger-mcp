"""OIDC discovery: resolve JWKS and token endpoints from any IdP.

Reads ``{issuer}/.well-known/openid-configuration`` so the server is not tied
to a specific provider's URL layout (Keycloak, Authentik, Auth0, Okta, …).
Explicit overrides win and skip the network call. Resolution is a one-off,
synchronous call done at startup.
"""

from __future__ import annotations

import httpx


class OidcDiscoveryError(RuntimeError):
    pass


def discover_endpoints(
    issuer: str,
    *,
    jwks_uri: str | None = None,
    token_endpoint: str | None = None,
    timeout: float = 10.0,
) -> tuple[str, str]:
    """Return ``(jwks_uri, token_endpoint)`` for ``issuer``.

    Uses explicit overrides where given; otherwise fetches the IdP's discovery
    document. Raises :class:`OidcDiscoveryError` if a needed value can't be
    resolved.
    """
    if jwks_uri and token_endpoint:
        return jwks_uri, token_endpoint

    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        resp = httpx.get(url, timeout=timeout)
        resp.raise_for_status()
        doc = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OidcDiscoveryError(f"OIDC discovery failed for {url}: {exc}") from exc

    resolved_jwks = jwks_uri or doc.get("jwks_uri")
    resolved_token = token_endpoint or doc.get("token_endpoint")
    if not resolved_jwks or not resolved_token:
        raise OidcDiscoveryError(
            f"discovery document at {url} is missing jwks_uri/token_endpoint"
        )
    return resolved_jwks, resolved_token
