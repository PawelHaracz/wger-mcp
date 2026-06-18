#!/usr/bin/env python3
"""Fetch an OAuth2 access token from an OIDC provider (Keycloak, ...).

Used to obtain a *user* token for testing — it stands in for what a real MCP
client (e.g. Claude) would acquire via OAuth. Works with public or confidential
clients (pass --secret / OIDC_CLIENT_SECRET for the latter).

Modes:
  - device   : OAuth 2.0 Device Authorization Grant (log in via browser)
  - password : Resource Owner Password Credentials (non-interactive)

Usage:
  uv run python scripts/get_token.py device \\
      --issuer https://auth/realms/x --client wger-mcp --secret "$OIDC_CLIENT_SECRET"
  uv run python scripts/get_token.py password \\
      --issuer https://auth/realms/x --client wger-mcp --user alice

Progress (verification URL etc.) goes to stderr; with --raw only the raw
access_token is printed to stdout (handy for `TOK=$(... --raw)`).
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from urllib.parse import urljoin

import httpx

_VERIFY = os.environ.get("SSL_VERIFY", "1") != "0"


def _well_known(issuer: str) -> dict:
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    r = httpx.get(url, timeout=10.0, verify=_VERIFY)
    r.raise_for_status()
    return r.json()


def _with_secret(data: dict, secret: str | None) -> dict:
    return {**data, "client_secret": secret} if secret else data


def device_flow(issuer: str, client_id: str, secret: str | None, scope: str) -> dict:
    conf = _well_known(issuer)
    device_endpoint = conf.get("device_authorization_endpoint") or urljoin(
        conf["token_endpoint"].rsplit("/", 1)[0] + "/", "auth/device"
    )
    token_endpoint = conf["token_endpoint"]

    r = httpx.post(
        device_endpoint,
        data=_with_secret({"client_id": client_id, "scope": scope}, secret),
        timeout=15.0,
        verify=_VERIFY,
    )
    r.raise_for_status()
    init = r.json()
    verify_url = init.get("verification_uri_complete") or init["verification_uri"]
    print(f"\n>>> Open this URL and approve the login:\n    {verify_url}", file=sys.stderr)
    print(f">>> User code: {init['user_code']}\n", file=sys.stderr)

    interval = init.get("interval", 5)
    deadline = time.time() + init.get("expires_in", 600)
    while time.time() < deadline:
        time.sleep(interval)
        tr = httpx.post(
            token_endpoint,
            data=_with_secret(
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": client_id,
                    "device_code": init["device_code"],
                },
                secret,
            ),
            timeout=15.0,
            verify=_VERIFY,
        )
        if tr.status_code == 200:
            return tr.json()
        err = tr.json().get("error")
        if err in ("authorization_pending", "slow_down"):
            if err == "slow_down":
                interval += 5
            continue
        raise SystemExit(f"device flow failed: {tr.status_code} {tr.text}")
    raise SystemExit("device code expired")


def password_flow(
    issuer: str, client_id: str, secret: str | None, user: str, password: str, scope: str
) -> dict:
    conf = _well_known(issuer)
    r = httpx.post(
        conf["token_endpoint"],
        data=_with_secret(
            {
                "grant_type": "password",
                "client_id": client_id,
                "username": user,
                "password": password,
                "scope": scope,
            },
            secret,
        ),
        timeout=15.0,
        verify=_VERIFY,
    )
    if r.status_code != 200:
        raise SystemExit(f"password flow failed: {r.status_code} {r.text}")
    return r.json()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["device", "password"])
    ap.add_argument(
        "--issuer",
        default=os.environ.get("OIDC_ISSUER"),
        help="OIDC issuer URL (or set OIDC_ISSUER)",
    )
    ap.add_argument(
        "--client",
        default=os.environ.get("OIDC_CLIENT_ID"),
        help="OAuth2 client_id (or set OIDC_CLIENT_ID)",
    )
    ap.add_argument(
        "--secret",
        default=os.environ.get("OIDC_CLIENT_SECRET"),
        help="client secret for a confidential client (or set OIDC_CLIENT_SECRET)",
    )
    ap.add_argument("--user", help="username (password flow)")
    ap.add_argument("--scope", default="openid profile email")
    ap.add_argument("--raw", action="store_true", help="print only the access_token")
    ap.add_argument(
        "--export", action="store_true", help="emit `export MCP_TOKEN=...` for shell sourcing"
    )
    args = ap.parse_args()
    if not args.issuer:
        sys.exit("--issuer is required (or set OIDC_ISSUER)")
    if not args.client:
        sys.exit("--client is required (or set OIDC_CLIENT_ID)")

    if args.mode == "device":
        tok = device_flow(args.issuer, args.client, args.secret, args.scope)
    else:
        if not args.user:
            sys.exit("--user is required for password mode")
        pw = os.environ.get("KC_PASSWORD") or getpass.getpass("password: ")
        tok = password_flow(args.issuer, args.client, args.secret, args.user, pw, args.scope)

    if args.raw:
        print(tok["access_token"])
    elif args.export:
        print(f"export MCP_TOKEN={tok['access_token']}")
    else:
        print(json.dumps(tok, indent=2))


if __name__ == "__main__":
    main()
