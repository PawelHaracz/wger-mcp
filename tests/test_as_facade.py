"""AuthorizationServerFacade: AS metadata, /authorize 302, /token reverse-proxy.

The facade lets a client that treats this origin as the OAuth authorization
server (e.g. claude.ai) drive the flow against us while the real IdP stays
private: front-channel /authorize bounces the browser to the IdP, back-channel
/token is reverse-proxied to the IdP.
"""

from __future__ import annotations

import respx

from .conftest import AUTHORIZATION_ENDPOINT, OIDC_ENV, TOKEN_ENDPOINT, make_client


def _client(**overrides: str):
    return make_client(**{**OIDC_ENV, **overrides})


def test_as_metadata_advertises_facade_endpoints(mock_jwks: respx.MockRouter) -> None:
    with _client(MCP_PUBLIC_URL="https://mcp.test") as c:
        r = c.get("/.well-known/oauth-authorization-server")
        assert r.status_code == 200
        body = r.json()
        assert body["issuer"] == "https://mcp.test"
        assert body["authorization_endpoint"] == "https://mcp.test/authorize"
        assert body["token_endpoint"] == "https://mcp.test/token"
        assert body["code_challenge_methods_supported"] == ["S256"]


def test_as_metadata_derives_origin_from_forwarded_headers(
    mock_jwks: respx.MockRouter,
) -> None:
    """No MCP_PUBLIC_URL: endpoints follow the reverse-proxy/tunnel host."""
    with _client() as c:
        r = c.get(
            "/.well-known/oauth-authorization-server",
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "mcp.example.com"},
        )
        assert r.status_code == 200
        assert r.json()["authorization_endpoint"] == "https://mcp.example.com/authorize"


def test_authorize_redirects_to_idp_preserving_query(mock_jwks: respx.MockRouter) -> None:
    with _client() as c:
        q = (
            "response_type=code&client_id=wger-mcp"
            "&redirect_uri=https%3A%2F%2Fclaude.ai%2Fapi%2Fmcp%2Fauth_callback"
            "&code_challenge=abc123&code_challenge_method=S256&state=xyz"
        )
        r = c.get(f"/authorize?{q}", follow_redirects=False)
        assert r.status_code == 302
        loc = r.headers["location"]
        assert loc.startswith(AUTHORIZATION_ENDPOINT + "?")
        assert "client_id=wger-mcp" in loc
        assert "code_challenge=abc123" in loc
        assert "state=xyz" in loc
        # redirect_uri preserved (urlencoded) so the IdP validates the real one
        assert "redirect_uri=https%3A%2F%2Fclaude.ai%2Fapi%2Fmcp%2Fauth_callback" in loc


def test_authorize_is_public(mock_jwks: respx.MockRouter) -> None:
    """No bearer token needed to start the flow (302, not 401)."""
    with _client() as c:
        r = c.get(
            "/authorize?response_type=code&client_id=wger-mcp",
            follow_redirects=False,
        )
        assert r.status_code == 302


def test_token_reverse_proxies_to_idp(mock_jwks: respx.MockRouter) -> None:
    route = mock_jwks.post(TOKEN_ENDPOINT).respond(
        json={"access_token": "AT", "token_type": "Bearer", "expires_in": 300}
    )
    with _client() as c:
        r = c.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": "the-code",
                "code_verifier": "the-verifier",
                "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            },
        )
        assert r.status_code == 200
        assert r.json()["access_token"] == "AT"
        assert route.called
        sent = route.calls.last.request.content.decode()
        assert "grant_type=authorization_code" in sent
        assert "code_verifier=the-verifier" in sent


def test_facade_paths_are_overridable(mock_jwks: respx.MockRouter) -> None:
    """OAUTH_AUTHORIZE_PATH / OAUTH_TOKEN_PATH override the default root paths,
    in both the AS metadata and the live (auth-bypassed) routes."""
    with _client(
        MCP_PUBLIC_URL="https://mcp.test",
        OAUTH_AUTHORIZE_PATH="/oauth/authorize",
        OAUTH_TOKEN_PATH="/oauth/token",
    ) as c:
        meta = c.get("/.well-known/oauth-authorization-server").json()
        assert meta["authorization_endpoint"] == "https://mcp.test/oauth/authorize"
        assert meta["token_endpoint"] == "https://mcp.test/oauth/token"
        # the overridden authorize path is served and public (302, not 401)
        r = c.get(
            "/oauth/authorize?response_type=code&client_id=wger-mcp",
            follow_redirects=False,
        )
        assert r.status_code == 302
        # and the default root path is no longer wired → 401 (auth challenge)
        assert c.get("/authorize", follow_redirects=False).status_code == 401
