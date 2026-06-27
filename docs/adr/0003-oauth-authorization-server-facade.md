# OAuth Authorization-Server facade fronting the IdP

**Status:** accepted (2026-06-19)

## Context

We support MCP-native OAuth so interactive clients can obtain an inbound token.
The spec-correct shape (RFC 9728) is: our protected-resource metadata lists the
real IdP under `authorization_servers`, and the client fetches the IdP's metadata
and drives `/authorize` + `/token` against the **IdP**.

In practice that breaks with **claude.ai**'s custom connector, for two reasons:

1. It treats the **MCP server's own origin** as the authorization server — it
   fetches `{origin}/.well-known/oauth-authorization-server` and, when that 404s,
   falls back to `{origin}/authorize` + `{origin}/token`. It does not chase an
   `authorization_servers` pointer to a different host.
2. OAuth discovery and the back-channel token exchange run from Anthropic's
   cloud, so every OAuth endpoint must be reachable from the public internet. A
   private/LAN-only IdP (our case: Keycloak on an internal domain) is therefore
   unreachable, and the flow dead-ends.

## Decision

Expose a thin **Authorization-Server facade** in `oidc` mode, advertising *this*
origin as the AS and bridging to the IdP:

- `protected-resource` metadata sets `authorization_servers` to **self**.
- `/.well-known/oauth-authorization-server` returns RFC 8414 metadata whose
  `authorization_endpoint` / `token_endpoint` are on this origin (`/authorize`,
  `/token` by default — see note below).
- `/authorize` issues a `302` to the IdP's authorization endpoint with the
  query string intact (front-channel; the user's browser talks to the IdP).
- `/token` reverse-proxies the request to the IdP's token endpoint
  (back-channel; only this server talks to the IdP).

The facade paths default to the conventional root `/authorize` and `/token`
because some clients (claude.ai) ignore the metadata's `authorization_endpoint`
and assume those defaults relative to the origin. They are configurable via
`OAUTH_AUTHORIZE_PATH` / `OAUTH_TOKEN_PATH` for clients that expect otherwise.

The IdP's endpoints come from OIDC discovery (overridable via
`OIDC_AUTHORIZATION_ENDPOINT` / `OIDC_TOKEN_ENDPOINT`). `MCP_PUBLIC_URL` (or the
reverse-proxy `X-Forwarded-*`) determines the public origin in the metadata.

## Consequences

- The IdP stays private: only this server (public, e.g. behind a tunnel) and the
  user's browser (for the login redirect) touch it. Anthropic only ever reaches
  this origin.
- Tokens are still minted and signed by the IdP, so inbound validation
  (`iss` = IdP, JWKS from the IdP) and the downstream RFC 8693 token-exchange are
  unchanged — the facade only relays the handshake.
- The facade advertises **OAuth 2.0** authorization-server metadata, not OIDC, so
  the client treats the access token as an opaque bearer and does not validate an
  `id_token` issuer against our origin (which would mismatch the IdP's `iss`).
- The interactive `/authorize` is a redirect, so the **browser** must reach the
  IdP. With a LAN-only IdP that constrains where the user can run the login. The
  back-channel `/token` has no such constraint (always proxied).
- We do not advertise a `registration_endpoint`: clients use a pre-registered
  confidential client (`OIDC_CLIENT_ID`), not Dynamic Client Registration.
