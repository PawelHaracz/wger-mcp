# Quickstart: wger API key (MCP_AUTH=none)

Use this setup when you run wger-mcp **locally or on a private network for a single user**. Inbound auth is disabled; every MCP call uses one static wger API key. The server prints a warning at startup to remind you not to expose it publicly.

---

## 1. Generate a wger API key

1. Sign in to your wger instance.
2. Click your **username → Settings** (top-right menu).
3. Open the **API** tab.
4. Click **Generate new API key**.
5. Copy the token shown — it is displayed only once.

Test that it works:

```bash
curl -fsS https://<your-wger>/api/v2/userprofile/ \
  -H "Authorization: Token <paste-token-here>"
```

A 200 response with your profile JSON means the token is valid.

---

## 2. Configure wger-mcp

Create (or edit) a `.env` file next to the server:

```ini
# Required: where wger lives
WGER_BASE_URL=https://wger.example.com

# Disable inbound auth; use the static token below for all wger calls
MCP_AUTH=none
WGER_DEV_TOKEN=<paste-wger-token-here>

# Optional: change listen address / port
# HOST=127.0.0.1
# PORT=8765
```

Start the server:

```bash
uv run wger-mcp
```

You should see:

```
INFO  wger_mcp: MCP_AUTH=none, MCP_PATH=/mcp
WARNING wger_mcp.auth.base: MCP_AUTH=none — incoming requests are NOT authenticated
```

---

## 3. Connect your MCP client

### Claude Code (CLI)

```bash
claude mcp add wger \
  --transport http \
  --scope user \
  http://localhost:8765/mcp
```

Verify the tool list loads:

```bash
claude mcp list
```

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "wger": {
      "type": "streamable-http",
      "url": "http://localhost:8765/mcp"
    }
  }
}
```

### curl smoke test

```bash
curl -fsS -X POST http://localhost:8765/mcp \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

A JSON response with `"serverInfo": {"name": "wger"}` confirms the server is reachable and the token works.

---

## Rotate the token

1. In wger UI → Settings → API → **Generate new API key**.
2. Replace `WGER_DEV_TOKEN` in `.env`.
3. Restart the server (`docker restart wger-mcp` or re-run `uv run wger-mcp`).

The old token is immediately invalidated by wger.

---

## Security notes

- `MCP_AUTH=none` means **any** process that can reach the server's port can call wger as you. Bind to `127.0.0.1` (set `HOST=127.0.0.1`) and never expose the port through a firewall or public proxy.
- For multi-user or internet-facing deployments, use `MCP_AUTH=oidc` (see [README.md](../README.md)).
