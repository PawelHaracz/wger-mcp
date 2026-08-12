# Context — wger MCP server

Glossary of the ubiquitous language for this project. Definitions only — no
implementation details. See `docs/adr/` for decisions.

## Terms

### Inbound auth

How an MCP *client* (Claude Desktop, a script, …) proves its identity to the
MCP server. Selectable via `MCP_AUTH` (`oidc` | `static_token` | `none`). Gates
every `/mcp/*` request except the public paths (`/health`, `/.well-known/*`,
and the [[AS facade]] endpoints).

### Outbound auth

How the MCP server proves identity to the upstream **wger** REST API. Under
`oidc` this is per request, as the specific [[wger identity]] derived from the
inbound credential, using a [[wger JWT]] obtained by [[Token exchange]]. Under
the single-user strategies it is a static DRF API key (`WGER_DEV_TOKEN`) shared
by every request. The username/password web-form session is **removed**.

### wger identity

The wger user account whose data an operation reads or writes. Under `oidc` it
varies per request and is derived from the inbound credential; under the
single-user strategies it is fixed (the owner of `WGER_DEV_TOKEN`).

### Single-user vs multi-user

- **Multi-user:** each client maps to its own wger account; the MCP performs
  every operation as that specific wger identity. Requires an [[IdP]].
  *(`MCP_AUTH=oidc`, the default.)*
- **Single-user:** the whole MCP server acts as one wger account, via a static
  API key and no IdP. Two variants differing only in whether inbound requests
  are authenticated: `static_token` validates a shared secret and is safe to
  expose over TLS; `none` performs no inbound authentication at all and is
  localhost-only. *(Re-introduced 2026-08-12 for self-hosting; the earlier
  removal on 2026-06-18 left no IdP-free option that was safe to expose.)*

### Pass-through

The model where the inbound credential **is** (or directly yields) the outbound
credential: a wger-issued token presented by the client is forwarded by the MCP
to wger, so no per-user secrets are stored server-side. *(Not chosen — see
[[Token exchange]].)*

### IdP (identity provider)

The external single sign-on authority both wger and the MCP trust — **any OIDC
provider** (Keycloak, Authentik, Auth0, Okta, …); endpoints are taken from its
discovery document, so the MCP is not provider-locked. wger must be wired to the
same IdP as an OIDC social-login provider; the MCP validates the same
IdP-issued tokens. Not required by the single-user strategies.

### Token exchange

Turning a verified [[IdP]] token into a **native wger credential**, because
wger's REST API only accepts wger-native tokens (DRF `Token`, wger-issued JWT,
or session) — never a foreign IdP token. Two steps:

1. The MCP is a **confidential OIDC client** and uses RFC 8693 to exchange the
   inbound token for an **access_token** whose `aud` is wger's OIDC client.
2. The MCP posts that token (under `token.id_token`) to wger's allauth headless
   `/allauth/app/v1/auth/provider/token`, and wger returns a [[wger JWT]].
   Requires the user to have **no wger-side MFA** (MFA delegated to the IdP).

### wger JWT

A wger-issued, RS256, `Authorization: Bearer` token accepted by the wger REST
API. Two flavours, both Bearer: allauth-headless JWT (from the exchange) and
SimpleJWT. Access token lives ~5 min; refresh ~120 days and **rotates**
(single-use, blacklist-after-rotation).

### AS facade

The server presenting **itself** as the OAuth authorization server while
bridging to the real [[IdP]]. For clients that treat the MCP origin as the AS
(e.g. claude.ai) and can't reach a private IdP directly: it serves AS metadata,
`302`s `/authorize` to the IdP (front-channel), and reverse-proxies
`/token` to the IdP (back-channel). Those paths are the defaults clients assume
(override via `OAUTH_AUTHORIZE_PATH` / `OAUTH_TOKEN_PATH`). The IdP still mints
the tokens; the facade only relays. See `docs/adr/0003-*.md`.
