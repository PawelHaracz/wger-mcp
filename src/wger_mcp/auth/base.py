"""Common helpers for auth middlewares."""

from __future__ import annotations

import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .identity import Identity, reset_identity, set_identity

log = logging.getLogger(__name__)

_BYPASS_EXACT = {"/health"}


def is_bypass_path(path: str, extra: set[str] | None = None) -> bool:
    """Public paths that skip inbound auth: health, OAuth discovery metadata, and
    the AS-facade endpoints (``extra``; they carry their own OAuth client auth)."""
    return (
        path in _BYPASS_EXACT
        or (extra is not None and path in extra)
        or path.startswith("/health/")
        or path.startswith("/.well-known/")
    )


async def reply_unauthorized(
    scope: Scope, receive: Receive, send: Send, *, reason: str, www_authenticate: str
) -> None:
    resp = JSONResponse(
        {"error": "unauthorized", "reason": reason},
        status_code=401,
        headers={"www-authenticate": www_authenticate},
    )
    await resp(scope, receive, send)


class ApiKeyAuthMiddleware:
    """Inbound auth for ``MCP_AUTH=apikey``.

    Each MCP client passes its own wger DRF API key as:
        Authorization: Token <wger-api-key>

    The middleware extracts it, stores it in the per-request :class:`Identity`,
    and the :class:`~wger_mcp.auth.exchange.WgerTokenProvider` forwards it
    verbatim to wger (no OIDC involved).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if is_bypass_path(path):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        raw_auth = headers.get(b"authorization", b"").decode()
        if not raw_auth.lower().startswith("token "):
            await reply_unauthorized(
                scope,
                receive,
                send,
                reason="missing or invalid Authorization header; expected 'Token <wger-api-key>'",
                www_authenticate='Token realm="wger-mcp"',
            )
            return
        api_key = raw_auth[6:].strip()
        if not api_key:
            await reply_unauthorized(
                scope,
                receive,
                send,
                reason="empty API key",
                www_authenticate='Token realm="wger-mcp"',
            )
            return
        token = set_identity(
            Identity(subject=api_key, username=None, inbound_token=api_key, strategy="apikey")
        )
        try:
            await self.app(scope, receive, send)
        finally:
            reset_identity(token)


class NoAuthMiddleware:
    """No-op middleware. Use only for local dev (``MCP_AUTH=none``).

    Binds a fixed dev :class:`Identity`; the wger client then uses the static
    ``WGER_DEV_TOKEN`` for outbound calls.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        log.warning("MCP_AUTH=none — incoming requests are NOT authenticated")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = set_identity(Identity(subject="local-dev", username="local-dev", strategy="none"))
        try:
            await self.app(scope, receive, send)
        finally:
            reset_identity(token)
