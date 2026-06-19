#!/usr/bin/env bash
# End-to-end live test: start the wger-mcp server with a real env file, then
# drive it as an MCP client (initialize + read-only tool calls).
#
# Usage:  bash scripts/e2e.sh [env-file]      (default: .env.probe)
# The env file must set the wger/Keycloak config and SUBJECT_TOKEN (a Keycloak
# user access token used as the inbound Bearer).
set -euo pipefail
cd "$(dirname "$0")/.."

ENVFILE="${1:-.env.probe}"
[ -f "$ENVFILE" ] || { echo "missing $ENVFILE (cp .env.probe.example .env.probe and fill it)"; exit 1; }
set -a; . "./$ENVFILE"; set +a

# No pre-supplied user token? Log in via Keycloak device flow — the harness
# plays the MCP client, exactly as Claude would (you approve once in a browser).
if [ -z "${SUBJECT_TOKEN:-}" ]; then
    echo "SUBJECT_TOKEN empty — logging in via Keycloak device flow ..."
    SUBJECT_TOKEN="$(uv run python scripts/get_token.py device --raw)" || {
        echo "device-flow login failed (is 'OAuth 2.0 Device Authorization Grant' enabled on $OIDC_CLIENT_ID?)"; exit 1; }
    export SUBJECT_TOKEN
    echo "got user token via device flow."
fi

PORT="${PORT:-8765}"
echo "starting server on :$PORT (MCP_AUTH=${MCP_AUTH:-oidc}) ..."
uv run wger-mcp >/tmp/wger-mcp-e2e.log 2>&1 &
SRV=$!
trap 'kill "$SRV" 2>/dev/null || true' EXIT

# Wait for /health without a foreground sleep (retry on connection refused).
if ! curl -sf --retry 40 --retry-delay 1 --retry-connrefused --retry-all-errors \
        "http://127.0.0.1:${PORT}/health" >/dev/null; then
    echo "server did not come up — last log lines:"; tail -20 /tmp/wger-mcp-e2e.log; exit 1
fi
echo "server healthy; driving MCP client ..."
echo "============================================================"
uv run python scripts/e2e_call.py --url "http://127.0.0.1:${PORT}${MCP_PATH:-/mcp}" \
    --token "${SUBJECT_TOKEN:-}"
rc=$?
echo "============================================================"
echo "(server log: /tmp/wger-mcp-e2e.log)"
exit "$rc"
