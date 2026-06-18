#!/usr/bin/env python3
"""End-to-end probe for the Keycloak -> wger token-exchange chain.

Exercises the *real* TokenExchanger + WgerClient against a live Keycloak and
wger 2.6, printing each hop so the infra assumptions (RFC 8693 enabled,
provider/token contract, allauth provider id) can be confirmed without the MCP
transport layer.

Usage:
  # 1) get an inbound Keycloak token for a test user (any client works as the
  #    subject token; the exchange re-audiences it):
  uv run python scripts/get_token.py device \
      --issuer https://auth.example.com/realms/main --client wger-mcp
  # 2) probe the chain with that token:
  OIDC_ISSUER=https://auth.example.com/realms/main \
  OIDC_CLIENT_ID=wger-mcp OIDC_CLIENT_SECRET=... \
  WGER_OIDC_AUDIENCE=wger WGER_BASE_URL=https://wger.example.com \
  uv run python scripts/probe_exchange.py --subject-token "<keycloak access token>"

All connection params default to the same env vars the server reads.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

# Make `src/` importable when run from a checkout without an install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from wger_mcp.auth.exchange import (
    TokenExchanger,
    WgerTokenError,
    WgerTokenProvider,
)
from wger_mcp.auth.identity import Identity, reset_identity, set_identity
from wger_mcp.wger_client import WgerClient, WgerError


def _env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if not val:
        sys.exit(f"missing required env/arg: {name}")
    return val


def _derive(issuer: str, suffix: str, override: str | None) -> str:
    return override or issuer.rstrip("/") + suffix


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--subject-token", default=os.environ.get("SUBJECT_TOKEN"),
                    help="inbound Keycloak token to exchange (or SUBJECT_TOKEN env)")
    ap.add_argument("--provider", default=os.environ.get("WGER_ALLAUTH_PROVIDER", "openid_connect"))
    args = ap.parse_args()
    if not args.subject_token:
        sys.exit("missing --subject-token (or SUBJECT_TOKEN env)")

    issuer = _env("OIDC_ISSUER")
    wger_base = _env("WGER_BASE_URL").rstrip("/")
    token_endpoint = _derive(issuer, "/protocol/openid-connect/token",
                             os.environ.get("OIDC_TOKEN_ENDPOINT"))
    provider_token_url = wger_base + os.environ.get(
        "WGER_ALLAUTH_PROVIDER_TOKEN_PATH", "/allauth/app/v1/auth/provider/token"
    )

    print(f"token_endpoint     : {token_endpoint}")
    print(f"provider_token_url : {provider_token_url}")
    print(f"wger api root      : {wger_base}/api/v2")
    print(f"provider id        : {args.provider}")
    print(f"wger audience      : {_env('WGER_OIDC_AUDIENCE')}")
    print("-" * 60)

    ex = TokenExchanger(
        token_endpoint=token_endpoint,
        client_id=_env("OIDC_CLIENT_ID"),
        client_secret=_env("OIDC_CLIENT_SECRET"),
        wger_audience=_env("WGER_OIDC_AUDIENCE"),
        provider_token_url=provider_token_url,
        provider=args.provider,
    )
    identity = Identity(subject="probe", inbound_token=args.subject_token)
    client = WgerClient(f"{wger_base}/api/v2", WgerTokenProvider(exchanger=ex))
    ctx = set_identity(identity)
    try:
        # Hop 1+2: Keycloak token-exchange -> wger provider/token -> wger JWT.
        try:
            wger_jwt = await ex.wger_token_for(identity)
        except WgerTokenError as exc:
            print(f"[FAIL] exchange chain: {exc}")
            return 2
        print(f"[OK] obtained wger JWT ({len(wger_jwt)} chars): {wger_jwt[:24]}…")

        # Hop 3: call the wger REST API as that user.
        try:
            profile = await client.get("userprofile/")
        except WgerError as exc:
            print(f"[FAIL] GET /api/v2/userprofile/: {exc.status} {exc.body}")
            return 3
        results = profile.get("results", profile) if isinstance(profile, dict) else profile
        print(f"[OK] GET /api/v2/userprofile/ → {str(results)[:200]}")
        print("\nALL GREEN — the exchange chain works end to end.")
        return 0
    finally:
        reset_identity(ctx)
        await client.aclose()  # closes the provider + exchanger too


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
