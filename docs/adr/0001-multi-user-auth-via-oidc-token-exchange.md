# Multi-user wger access via OIDC token-exchange

**Status:** accepted (2026-06-18); partially amended by
[0004](0004-static-token-strategy-for-single-user.md), which re-introduces a
single-user strategy for deployments without an identity provider.

## Decision

wger 2.6 added OIDC SSO (allauth social login + 2FA) and issues its own RS256
JWTs; its REST API accepts wger-native credentials only (DRF `Token`,
wger-issued JWT, or session) — never a foreign IdP token. We replace the
previous single-user model (one static `WGER_API_TOKEN` for the whole server)
with a **multi-user** model in which every request acts as the caller's own
wger account.

The MCP is a **confidential OIDC client** of a generic SSO provider (any OIDC
IdP — Keycloak, Authentik, Auth0, Okta, …; endpoints come from the IdP's
discovery document). Per request it: validates the inbound OIDC token (JWKS);
uses RFC 8693 token-exchange to obtain a token whose audience is wger's OIDC
client; posts that to wger's allauth headless
`/allauth/app/v1/auth/provider/token` to receive a wger JWT; and calls
`/api/v2/*` with that `Bearer` token. Clients obtain their OIDC token either via
MCP-native OAuth (the IdP as authorization server) or by presenting a Bearer
token directly. The wger access token (~5 min) is cached in memory per user; on
expiry the MCP re-runs the exchange rather than storing wger's rotating refresh
tokens.

## Considered options

- **Pass-through of a wger JWT** (client logs into wger, sends the wger token,
  MCP forwards it). Rejected: pushes the wger-login dance onto every client and
  couples clients to wger's auth instead of the central IdP.
- **Per-user stored wger tokens** (each user registers a long-lived wger API
  key; MCP maps identity → token). Rejected for the SSO goal — but note this is
  wger's blessed path for MFA-enforced accounts (see Consequences).
- **Loosening wger-side validation** to accept the MCP's audience directly on
  the REST API. Rejected: weakens wger security, couples the MCP's identity to
  wger config.
- **Keeping single-user / static token.** Still works on 2.6 but cannot
  represent per-caller identity. Rejected for the multi-user goal.

## Consequences

Validated end-to-end against a live wger 2.6 + Keycloak; the following are
load-bearing and were learned in the process:

- **Exchange must request an `access_token`, sent under `token.id_token`.** A
  requested *id_token* is audienced at the requesting client, not wger, and
  wger's allauth `openid_connect.verify_token` rejects it. The exchanged
  *access_token* carries `aud=<wger client>` and is accepted.
- **The IdP must permit the exchange to wger's audience.** In Keycloak this
  means the MCP client needs Standard Token Exchange enabled and an Audience
  mapper that makes the wger client an available audience (otherwise:
  `Requested audience not available`).
- **wger-side MFA blocks the headless login.** wger 2.6's `provider/token`
  enforces allauth MFA: if the user has a TOTP/WebAuthn authenticator enrolled
  *in wger*, login returns a pending MFA challenge and no JWT is issued — a
  server-side exchange cannot complete it, and there is no setting to skip MFA
  for SSO logins. Therefore **MFA must be delegated to the IdP**: users must not
  enroll wger-side 2FA. If a deployment requires wger-enforced MFA, this model
  is unusable and per-user wger API keys are the fallback.
- The MCP becomes stateful per request (in-memory token cache).
- The static `WGER_API_TOKEN`, the `WGER_USERNAME/PASSWORD` web-form session,
  and the `create_ingredient` tool (which depended on it) are removed.
- Inbound auth narrows to OIDC; the `api_key` and `proxy_header` strategies are
  dropped (`none` remains for local dev).
