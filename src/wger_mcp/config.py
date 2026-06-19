"""Settings for wger-mcp.

Since wger 2.6, the server is **multi-user**: every request acts as the
caller's own wger account. Authentication has two halves that share one
SSO identity provider (any OIDC IdP — Keycloak, Authentik, Auth0, Okta, …):

- **Inbound** — the client presents an OIDC-issued token (via MCP-native OAuth
  or out-of-band). The server validates it against the IdP's JWKS.
- **Outbound** — the server is a *confidential* OIDC client. It exchanges the
  inbound token (RFC 8693) for one whose audience is wger's OIDC client, posts
  that to wger's allauth headless ``provider/token`` endpoint, and uses the
  returned wger JWT as ``Authorization: Bearer`` on the wger REST API. See
  ``docs/adr/0001-multi-user-auth-via-oidc-token-exchange.md``.

Endpoints (JWKS, token) are resolved from the IdP's discovery document
(``{issuer}/.well-known/openid-configuration``) unless overridden.

``MCP_AUTH=none`` is a local-dev-only escape hatch: it skips SSO entirely and
calls wger with a static ``WGER_DEV_TOKEN`` (a personal DRF API key).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, HttpUrl, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthStrategy(StrEnum):
    oidc = "oidc"
    none = "none"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="",
    )

    # ---------- upstream wger ----------
    wger_base_url: HttpUrl

    # ---------- inbound auth strategy ----------
    mcp_auth: AuthStrategy = AuthStrategy.oidc

    # ---- SSO identity provider (OIDC) ----
    # Realm/tenant issuer, e.g. https://idp.example.com/realms/main (Keycloak)
    # or https://tenant.auth0.com/. The same IdP wger uses for OIDC login.
    oidc_issuer: HttpUrl | None = None
    # Resolved from the discovery document when omitted.
    oidc_jwks_uri: HttpUrl | None = None
    oidc_token_endpoint: HttpUrl | None = None
    oidc_authorization_endpoint: HttpUrl | None = None

    # Inbound-token validation.
    mcp_oidc_audience: str | None = None  # if set, inbound 'aud'/'azp' must contain it
    mcp_oidc_algorithms: list[str] = Field(default_factory=lambda: ["RS256"])
    mcp_oidc_username_claim: str = "preferred_username"
    mcp_oidc_allowed_users: list[str] = Field(default_factory=list)
    mcp_jwks_ttl_seconds: int = 3600

    # ---- token exchange (this server as a confidential OIDC client) ----
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    # Target audience of the exchange = wger's OIDC client id at the IdP.
    wger_oidc_audience: str | None = None

    # ---- wger allauth headless exchange ----
    # The allauth provider id of the OIDC connection configured in wger
    # (SocialApp.provider_id). For a generic OIDC connection this is the slug
    # set in wger's admin; it is often — but not always — "openid_connect".
    # The exchange requests an access_token aud'd at wger so verify_token accepts it.
    wger_allauth_provider: str = "openid_connect"
    wger_allauth_provider_token_path: str = "/allauth/app/v1/auth/provider/token"

    # ---- local-dev escape hatch (MCP_AUTH=none) ----
    # A personal wger DRF API key, sent as 'Authorization: Token <...>'.
    wger_dev_token: str | None = None

    # ---------- transport ----------
    host: str = "0.0.0.0"
    port: int = 8765
    mcp_path: str = "/mcp"
    # Externally reachable base URL of this server, used as the OAuth
    # protected-resource identifier and in metadata. Falls back to host:port.
    mcp_public_url: HttpUrl | None = None

    # DNS rebinding protection. Empty list disables the check.
    allowed_hosts: list[str] = Field(default_factory=list)

    @field_validator("mcp_oidc_algorithms", mode="after")
    @classmethod
    def _normalize_algs(cls, v: list[str]) -> list[str]:
        return [a.strip().upper() for a in v if a.strip()]

    @model_validator(mode="after")
    def _check_strategy_requirements(self) -> Settings:
        if self.mcp_auth is AuthStrategy.oidc:
            missing = [
                name
                for name, val in (
                    ("OIDC_ISSUER", self.oidc_issuer),
                    ("OIDC_CLIENT_ID", self.oidc_client_id),
                    ("OIDC_CLIENT_SECRET", self.oidc_client_secret),
                    ("WGER_OIDC_AUDIENCE", self.wger_oidc_audience),
                )
                if not val
            ]
            if missing:
                raise ValueError("MCP_AUTH=oidc requires: " + ", ".join(missing))
        elif self.mcp_auth is AuthStrategy.none and not self.wger_dev_token:
            raise ValueError("MCP_AUTH=none requires WGER_DEV_TOKEN (a wger DRF API key)")
        return self

    # ---------- derived ----------
    @property
    def wger_api_root(self) -> str:
        return str(self.wger_base_url).rstrip("/") + "/api/v2"

    @property
    def provider_token_url(self) -> str:
        return str(self.wger_base_url).rstrip("/") + self.wger_allauth_provider_token_path


def _csv_to_json_list(name: str) -> None:
    """Allow comma-separated values for list-typed env vars."""
    import os

    if name not in os.environ:
        return
    raw = os.environ[name].strip()
    if not raw:
        os.environ[name] = "[]"
        return
    if raw.startswith("["):
        return
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    os.environ[name] = "[" + ",".join(f'"{p}"' for p in parts) + "]"


_CSV_VARS = (
    "MCP_OIDC_ALGORITHMS",
    "MCP_OIDC_ALLOWED_USERS",
    "ALLOWED_HOSTS",
)


def load_settings() -> Settings:
    for var in _CSV_VARS:
        _csv_to_json_list(var)
    return Settings()  # type: ignore[call-arg]
