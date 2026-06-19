# Context — wger-mcp

Glossary of the ubiquitous language for this project. Definitions only — no
implementation details. See `docs/adr/` for decisions.

## Terms

### Inbound auth

How an MCP *client* (Claude Desktop, a script, …) proves its identity to the
wger-mcp server. Today selectable via `MCP_AUTH` (api_key | jwt | proxy_header |
none). Gates every `/mcp/*` request.

### Outbound auth

How the wger-mcp server proves identity to the upstream **wger** REST API.
Per request, as the specific [[wger identity]] derived from the inbound
credential, using a [[wger JWT]] obtained by [[Token exchange]]. The legacy
single static DRF token (and the username/password web-form session) is
**removed**.

### wger identity

The wger user account whose data an operation reads or writes. Currently fixed
(the owner of the outbound token); under the multi-user model it varies
per request and is derived from the inbound credential.

### Single-user vs multi-user

- **Single-user:** the whole MCP server acts as one wger account. *(Removed —
  2026-06-18.)*
- **Multi-user:** each client maps to its own wger account; the MCP performs
  every operation as that specific wger identity. *(The only supported model —
  2026-06-18.)*

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
IdP-issued tokens. *(Concretely a self-hosted Keycloak here — 2026-06-18.)*

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
`302`s `/oauth/authorize` to the IdP (front-channel), and reverse-proxies
`/oauth/token` to the IdP (back-channel). The IdP still mints the tokens; the
facade only relays. See `docs/adr/0003-*.md`.
