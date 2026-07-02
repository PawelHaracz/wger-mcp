"""OAuth 2.0 Authorization Server facade (RFC 8414) fronting an external IdP.

claude.ai's MCP connector treats the MCP server's own origin as the
authorization server: it discovers ``{origin}/.well-known/oauth-authorization-server``
and drives ``/authorize`` + ``/token`` against that same origin. It does **not**
follow the ``authorization_servers`` pointer to a different host.

When the real IdP (e.g. Keycloak) is not reachable by the client/Anthropic —
typically because the MCP server is exposed via a tunnel but the IdP stays on a
private network — we expose a thin facade:

- advertise *this* origin as the authorization server,
- ``/authorize`` → 302 the browser to the IdP's authorization endpoint
  (the user's browser reaches the IdP directly; cookies/login stay on the IdP),
- ``/token`` → reverse-proxy the back-channel token request to the IdP.

(Paths default to the conventional ``/authorize`` / ``/token``; override with
``OAUTH_AUTHORIZE_PATH`` / ``OAUTH_TOKEN_PATH``.)

The IdP never has to be publicly reachable; the client only ever talks to this
origin. Tokens are still minted and signed by the IdP, so the inbound validation
in :mod:`.oidc` (issuer = IdP) is unchanged.
"""

from __future__ import annotations

import logging

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

log = logging.getLogger(__name__)

# Default facade endpoint paths. Conventional root paths because clients like
# claude.ai assume them and ignore the authorization_endpoint in the AS metadata.
# Overridable per-deployment via OAUTH_AUTHORIZE_PATH / OAUTH_TOKEN_PATH (config).
AUTHORIZE_PATH = "/authorize"
TOKEN_PATH = "/token"
AS_METADATA_PATH = "/.well-known/oauth-authorization-server"


class AuthorizationServerFacade:
    """Presents this origin as an OAuth AS, bridging to an external IdP."""

    def __init__(
        self,
        *,
        idp_authorization_endpoint: str,
        idp_token_endpoint: str,
        authorize_path: str = AUTHORIZE_PATH,
        token_path: str = TOKEN_PATH,
        timeout: float = 15.0,
    ) -> None:
        self._idp_authorize = idp_authorization_endpoint
        self._idp_token = idp_token_endpoint
        self._authorize_path = authorize_path
        self._token_path = token_path
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    def metadata(self, origin: str) -> dict:
        """RFC 8414 metadata advertising this origin's facade endpoints."""
        base = origin.rstrip("/")
        return {
            "issuer": base,
            "authorization_endpoint": base + self._authorize_path,
            "token_endpoint": base + self._token_path,
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": [
                "client_secret_post",
                "client_secret_basic",
            ],
            "scopes_supported": ["openid", "profile", "email", "offline_access"],
        }

    async def authorize(self, request: Request) -> Response:
        """Front-channel: bounce the browser to the IdP, query string intact.

        Everything the IdP needs (client_id, redirect_uri, PKCE challenge, state,
        scope) is in the query and is preserved verbatim, so the IdP validates it
        against the real client. The IdP redirects straight back to the client's
        registered redirect_uri afterwards.
        """
        qs = request.url.query
        target = self._idp_authorize + (f"?{qs}" if qs else "")
        return RedirectResponse(target, status_code=302)

    async def token(self, request: Request) -> Response:
        """Back-channel: reverse-proxy the token request to the IdP verbatim.

        Forwards the urlencoded body plus the content-type, the client's
        Authorization header (client_secret_basic) and Accept, then returns the
        IdP's response unchanged. Client authentication is the IdP's job.
        """
        body = await request.body()
        headers = {}
        for h in ("content-type", "authorization", "accept"):
            v = request.headers.get(h)
            if v:
                headers[h] = v
        try:
            resp = await self._client.post(self._idp_token, content=body, headers=headers)
        except httpx.HTTPError as exc:
            log.warning("token-endpoint proxy to IdP failed: %s", exc)
            return JSONResponse(
                {"error": "temporarily_unavailable", "error_description": str(exc)},
                status_code=502,
            )
        out_headers = {}
        ct = resp.headers.get("content-type")
        if ct:
            out_headers["content-type"] = ct
        return Response(content=resp.content, status_code=resp.status_code, headers=out_headers)
