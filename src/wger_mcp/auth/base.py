"""Common helpers for auth middlewares."""

from __future__ import annotations

import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .identity import Identity, reset_identity, set_identity

log = logging.getLogger(__name__)

_BYPASS_EXACT = {"/health"}


def is_bypass_path(path: str) -> bool:
    """Public paths that skip auth: health checks and OAuth discovery metadata."""
    return (
        path in _BYPASS_EXACT
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
