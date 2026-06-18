#!/usr/bin/env python3
"""Drive the running wger-mcp server as a real MCP client (Streamable HTTP).

Connects with an inbound Bearer token (your Keycloak user token), runs
``initialize``, then calls a curated set of **read-only** tools and prints each
result. This exercises the full path: inbound JWKS validation → Keycloak
token-exchange → wger REST → tool result.

Usage:
  # server already running on :8765, token from env
  MCP_BEARER="<keycloak access token>" uv run python scripts/e2e_call.py
  # or pick one tool:
  uv run python scripts/e2e_call.py --token "<jwt>" --tool whoami
  uv run python scripts/e2e_call.py --token "<jwt>" \
      --tool search_exercises --args '{"query":"bench","limit":3}'
  # just enumerate tools:
  uv run python scripts/e2e_call.py --token "<jwt>" --list
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# Read-only smoke set — safe to run against live data.
DEFAULT_CALLS: list[tuple[str, dict]] = [
    ("whoami", {}),
    ("list_routines", {}),
    ("list_nutrition_plans", {}),
    ("get_body_weight_history", {"limit": 3}),
    ("list_measurement_categories", {}),
    ("search_exercises", {"query": "bench", "limit": 3}),
    ("search_ingredients", {"query": "milk", "limit": 3}),
    ("weekly_summary", {"days": 7}),
]


def _summarize(result) -> str:
    if getattr(result, "structuredContent", None):
        body = json.dumps(result.structuredContent, ensure_ascii=False)
    else:
        parts = []
        for c in getattr(result, "content", []) or []:
            parts.append(getattr(c, "text", "") or str(c))
        body = " ".join(parts)
    flag = "ERROR " if getattr(result, "isError", False) else ""
    return flag + (body[:280] + ("…" if len(body) > 280 else ""))


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=os.environ.get("MCP_URL", "http://127.0.0.1:8765/mcp"))
    ap.add_argument(
        "--token", default=os.environ.get("MCP_BEARER") or os.environ.get("SUBJECT_TOKEN")
    )
    ap.add_argument("--list", action="store_true", help="just list available tools")
    ap.add_argument("--tool", help="call a single tool instead of the default set")
    ap.add_argument("--args", default="{}", help="JSON arguments for --tool")
    args = ap.parse_args()

    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    if not headers:
        print("warning: no --token / MCP_BEARER set (only works in MCP_AUTH=none)", file=sys.stderr)

    try:
        async with (
            streamablehttp_client(args.url, headers=headers) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            print(f"[OK] initialize → connected to {args.url}")

            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            print(f"[OK] tools/list → {len(names)} tools")
            if args.list:
                for n in names:
                    print(f"  - {n}")
                return 0

            calls = [(args.tool, json.loads(args.args))] if args.tool else DEFAULT_CALLS
            failures = 0
            for name, tool_args in calls:
                if name not in names:
                    print(f"[SKIP] {name}: not registered")
                    continue
                try:
                    res = await session.call_tool(name, tool_args)
                except Exception as exc:
                    print(f"[FAIL] {name}: {exc!r}")
                    failures += 1
                    continue
                line = _summarize(res)
                tag = "[FAIL]" if line.startswith("ERROR ") else "[OK]"
                if tag == "[FAIL]":
                    failures += 1
                print(f"{tag} {name}({json.dumps(tool_args)}) → {line}")
            print(f"\n{'ALL GREEN' if not failures else f'{failures} call(s) failed'}")
            return 1 if failures else 0
    except Exception as exc:
        print(f"[FAIL] could not drive MCP session: {exc!r}")
        return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
