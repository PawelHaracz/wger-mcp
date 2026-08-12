# A `static_token` strategy for single-user deployments

**Status:** accepted (2026-08-12)

Amends [0001](0001-multi-user-auth-via-oidc-token-exchange.md), which narrowed
inbound auth to OIDC and left `none` "for local dev".

## Context

After 0001 there were two inbound strategies:

- `oidc` — multi-user, but requires an identity provider.
- `none` — no inbound authentication whatsoever: anyone who can reach `/mcp`
  acts as the account behind the outbound API key.

That leaves a self-hoster who does not run an IdP with no safe option. Most
people running a personal wger instance do not have Keycloak or equivalent, and
standing one up purely to use this server is disproportionate. In practice the
gap invites the wrong workaround — exposing a `none` deployment behind TLS and
assuming TLS is the access control, which it is not.

The `none` strategy was also under-labelled: "local dev only" understates that
it performs *no* authentication.

## Decision

Add `MCP_AUTH=static_token`. Callers present a shared secret
(`MCP_STATIC_TOKEN`) as a bearer token; the server validates it and then calls
wger with the static API key (`WGER_DEV_TOKEN`), exactly as `none` does.

It is single-user like `none`, but inbound requests are authenticated, so it is
safe to expose over TLS.

Specifics:

- The secret is compared with `hmac.compare_digest`, so a wrong token leaks no
  timing signal.
- A 32-character minimum is enforced **at startup**, not on first request — the
  secret is the entire attack surface, so a guessable value should fail loudly
  at boot rather than silently serve traffic.
- The OAuth discovery documents are **not** served under this strategy. They are
  gated on the active strategy rather than on `OIDC_ISSUER` alone, because
  advertising an authorization server whose tokens this server never accepts
  sends clients through a flow that cannot succeed.

## Considered options

- **Docs only — clarify that `none` is unsafe.** Honest, but leaves the
  underlying gap: there is still no IdP-free way to reach the server remotely.
- **Per-user wger API keys.** Would restore multi-user without an IdP, but
  requires storing a secret per user server-side — the thing 0001 deliberately
  avoided — and there is no wger API to provision them.
- **Make wger itself the OIDC provider** (via django-allauth). The better
  long-term answer for multi-user without a third-party IdP, but it is a
  wger-side change, not one this repository can make.

## Consequences

- Single-user operation is supported again, deliberately and with an explicit
  security boundary — narrowing 0001's "the static token is removed" to "it is
  no longer the *only* model, and never the multi-user one".
- The shared secret grants full access to one wger account. Rotation means
  changing the variable and restarting; there is no revocation list.
- No MCP-native OAuth under this strategy, so clients must be configured with
  the token out-of-band.
- `none` remains, now documented as performing no inbound authentication and
  being localhost-only.
