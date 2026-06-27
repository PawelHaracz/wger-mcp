"""Inbound auth: validate an SSO (OIDC) token.

The client presents ``Authorization: Bearer <oidc-token>`` (obtained via
MCP-native OAuth with the IdP as the authorization server, or out-of-band).
The token is validated against the IdP's JWKS; the raw token is then carried
on the request :class:`Identity` so the outbound layer can exchange it for a
wger credential (see ``exchange.py``). Provider-agnostic — any OIDC IdP.
"""

from __future__ import annotations

import logging
import time

import httpx
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from .base import is_bypass_path, reply_unauthorized
from .identity import Identity, reset_identity, set_identity
from .oauth import WELL_KNOWN_PATH, forwarded_origin

log = logging.getLogger(__name__)


class JwksCache:
    def __init__(self, uri: str, ttl_seconds: int) -> None:
        self._uri = uri
        self._ttl = ttl_seconds
        self._keys: KeySet | None = None
        self._fetched_at: float = 0.0

    async def get(self, *, force: bool = False) -> KeySet:
        now = time.time()
        if force or self._keys is None or now - self._fetched_at > self._ttl:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(self._uri)
                resp.raise_for_status()
                self._keys = KeySet.import_key_set(resp.json())
                self._fetched_at = now
        return self._keys


def _aud_ok(claims: dict, audience: str | None) -> bool:
    if not audience:
        return True
    aud = claims.get("aud")
    if isinstance(aud, str):
        aud = [aud]
    if isinstance(aud, list) and audience in aud:
        return True
    # Many IdPs (e.g. Keycloak) put the client in `azp` rather than `aud`.
    return claims.get("azp") == audience


class OidcAuthMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        jwks_uri: str,
        issuer: str,
        audience: str | None,
        algorithms: list[str],
        username_claim: str,
        allowed_users: set[str],
        jwks_ttl_seconds: int = 3600,
        resource_metadata_url: str | None = None,
        public_paths: set[str] | None = None,
    ) -> None:
        self.app = app
        self._jwks = JwksCache(jwks_uri, jwks_ttl_seconds)
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        self._algorithms = algorithms or ["RS256"]
        self._username_claim = username_claim
        self._allowed = allowed_users
        self._resource_metadata_url = resource_metadata_url
        self._public_paths = public_paths or set()

        self._claims_registry = jwt.JWTClaimsRegistry(
            iss={"essential": True, "value": self._issuer},
            exp={"essential": True},
        )

    def _www_authenticate(self, request: Request) -> str:
        base = 'Bearer realm="wger-mcp"'
        url = self._resource_metadata_url
        if url is None:
            origin = forwarded_origin(request)
            url = origin + WELL_KNOWN_PATH if origin else None
        if url:
            base += f', resource_metadata="{url}"'
        return base

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if is_bypass_path(scope.get("path", ""), self._public_paths):
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        auth_header = request.headers.get("authorization", "")
        if not auth_header.lower().startswith("bearer "):
            await reply_unauthorized(
                scope, receive, send,
                reason="missing bearer token",
                www_authenticate=self._www_authenticate(request),
            )
            return

        token = auth_header.split(" ", 1)[1].strip()
        try:
            claims = await self._verify(token)
        except JoseError as exc:
            log.warning("oidc token rejected: %s", exc)
            await reply_unauthorized(
                scope, receive, send,
                reason=f"invalid token: {exc}",
                www_authenticate=self._www_authenticate(request),
            )
            return

        if not _aud_ok(claims, self._audience):
            await reply_unauthorized(
                scope, receive, send,
                reason="audience mismatch",
                www_authenticate=self._www_authenticate(request),
            )
            return

        username = claims.get(self._username_claim)
        if self._allowed and username not in self._allowed:
            log.warning("user %r not in allowed list", username)
            await reply_unauthorized(
                scope, receive, send,
                reason="user not allowed",
                www_authenticate=self._www_authenticate(request),
            )
            return

        subject = str(claims.get("sub") or username or "unknown")
        identity = Identity(
            subject=subject,
            username=username,
            inbound_token=token,
            strategy="oidc",
            claims=dict(claims),
        )
        ctx = set_identity(identity)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_identity(ctx)

    async def _verify(self, token: str) -> dict:
        keys = await self._jwks.get()
        try:
            decoded = jwt.decode(token, keys, algorithms=self._algorithms)
        except JoseError:
            keys = await self._jwks.get(force=True)
            decoded = jwt.decode(token, keys, algorithms=self._algorithms)
        self._claims_registry.validate(decoded.claims)
        return decoded.claims
