"""Cookie-based session client for wger's Django web views.

Used only when a tool needs to interact with an endpoint that isn't exposed
via wger's REST API — currently just the custom-ingredient submission form,
since `/api/v2/ingredient/` is a ReadOnlyModelViewSet at the source level.

Requires WGER_USERNAME / WGER_PASSWORD (separate from WGER_API_TOKEN). Logs
in lazily on first form submission and re-uses the session cookie thereafter.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx


class WgerSessionError(RuntimeError):
    def __init__(self, status: int, detail: Any) -> None:
        super().__init__(f"wger session error {status}: {detail}")
        self.status = status
        self.detail = detail


class WgerSession:
    def __init__(
        self,
        web_root: str,
        username: str,
        password: str,
        *,
        lang: str = "en",
        timeout: float = 20.0,
    ) -> None:
        self._web_root = web_root.rstrip("/")
        self._username = username
        self._password = password
        self._lang = lang
        self._client = httpx.AsyncClient(
            base_url=self._web_root,
            timeout=timeout,
            headers={"User-Agent": "wger-mcp/0.1 (session)"},
            follow_redirects=False,
        )
        self._logged_in = False
        self._login_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def lang(self) -> str:
        return self._lang

    @property
    def web_root(self) -> str:
        return self._web_root

    async def _csrf_token(self) -> str | None:
        return self._client.cookies.get("csrftoken")

    async def _ensure_login(self) -> None:
        if self._logged_in:
            return
        async with self._login_lock:
            if self._logged_in:
                return
            login_path = f"/{self._lang}/user/login"
            # Fetch the login form to obtain a CSRF cookie.
            try:
                await self._client.get(login_path, follow_redirects=True)
            except httpx.HTTPError as exc:
                raise WgerSessionError(503, f"login page fetch failed: {exc}") from exc
            csrf = await self._csrf_token()
            if not csrf:
                raise WgerSessionError(500, "no csrftoken cookie after GET login page")
            try:
                resp = await self._client.post(
                    login_path,
                    data={
                        "csrfmiddlewaretoken": csrf,
                        "username": self._username,
                        "password": self._password,
                    },
                    headers={"Referer": f"{self._web_root}{login_path}"},
                )
            except httpx.HTTPError as exc:
                raise WgerSessionError(503, f"login submit failed: {exc}") from exc
            # A 302 redirect to the dashboard (or /<lang>/) signals success;
            # a 200 re-renders the form with errors.
            if resp.status_code == 200:
                raise WgerSessionError(
                    401, "login rejected (check WGER_USERNAME / WGER_PASSWORD)"
                )
            if resp.status_code not in (301, 302, 303):
                raise WgerSessionError(
                    resp.status_code, "unexpected login response"
                )
            if not self._client.cookies.get("sessionid"):
                raise WgerSessionError(
                    401, "login redirect did not set sessionid cookie"
                )
            self._logged_in = True

    async def submit_form(
        self, path: str, data: dict[str, Any]
    ) -> tuple[int, str | None, str]:
        """Submit a Django form. Returns (status_code, redirect_location, body)."""
        await self._ensure_login()
        # GET the form page first to refresh CSRF for this view.
        try:
            await self._client.get(path)
        except httpx.HTTPError as exc:
            raise WgerSessionError(503, f"form GET failed: {exc}") from exc
        csrf = await self._csrf_token()
        if not csrf:
            raise WgerSessionError(500, "no csrftoken before form POST")
        payload = {**data, "csrfmiddlewaretoken": csrf}
        try:
            resp = await self._client.post(
                path,
                data=payload,
                headers={"Referer": f"{self._web_root}{path}"},
            )
        except httpx.HTTPError as exc:
            raise WgerSessionError(503, f"form POST failed: {exc}") from exc
        return resp.status_code, resp.headers.get("location"), resp.text

    @staticmethod
    def extract_id_from_redirect(
        location: str | None, resource: str
    ) -> int | None:
        """Pull a numeric id from a redirect like /en/nutrition/<resource>/<id>/view."""
        if not location:
            return None
        match = re.search(rf"/{resource}/(\d+)/", location)
        return int(match.group(1)) if match else None
