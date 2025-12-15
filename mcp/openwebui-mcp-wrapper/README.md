# OpenWebUI MCP Wrapper for Shifter

Custom OpenWebUI tools that enable AI-driven pentesting through the Shifter cyber range platform.

## Overview

This wrapper enables OpenWebUI to communicate with mcp-shifter using the standard MCP (Model Context Protocol) over Streamable HTTP transport. It handles:

1. User authentication via OAuth token forwarding
2. MCP session lifecycle (initialize → tools/list → tools/call)
3. Session management via `mcp-session-id` header
4. Error handling and session recovery

## Protocol Flow

```
OpenWebUI Tool                          mcp-shifter
     |                                       |
     |-- POST /mcp (initialize) ------------>|
     |   Authorization: Bearer <jwt>         |
     |   Accept: application/json, text/...  |
     |                                       |
     |<-- 200 + mcp-session-id header -------|
     |                                       |
     |-- POST /mcp (notifications/init) ---->|
     |   mcp-session-id: <id>                |
     |<-- 202 Accepted ---------------------|
     |                                       |
     |-- POST /mcp (tools/list) ------------>|
     |   mcp-session-id: <id>                |
     |<-- 200 {tools: [...]} ---------------|
     |                                       |
     |-- POST /mcp (tools/call) ------------>|
     |   mcp-session-id: <id>                |
     |<-- 200 {result: ...} ----------------|
```

## Installation

1. Log into OpenWebUI as an admin
2. Go to **Workspace** > **Tools**
3. Click **+** (Create Tool)
4. Copy the contents of `mcp_wrapper.py` into the editor
5. Click **Save**

## Configuration

After installation, configure the tool:

1. Click on the tool in the Tools list
2. Click the gear icon to access Valves (settings)
3. Configure:
   - **mcp_server_url**: URL of mcp-shifter (default: `http://mcp-shifter:3001`)
   - **request_timeout**: Timeout in seconds (default: 30)

## Available Tools

### list_mcp_tools

Lists all available MCP tools for your active Kali range.

**Example prompt**: "What tools do you have available?"

### run_mcp_tool

Executes an MCP tool on your Kali range.

**Parameters**:
- `tool_name`: Name of the tool to execute
- `arguments`: JSON string of arguments

**Example prompt**: "Run nmap against 10.1.1.100"

## Requirements

- OpenWebUI v0.6.31+
- User authenticated via Cognito SSO
- Active Shifter range in "ready" status
- mcp-shifter service running and accessible

## Development

```bash
# Install dependencies
uv sync --group dev

# Run tests
uv run python -m pytest -v

# Run tests with coverage
uv run python -m pytest --cov=. --cov-report=xml:coverage.xml
```

## Troubleshooting

### "Not authenticated. Please log in via SSO."

Your OAuth token is not available. Ensure you're logged in via the Cognito SSO flow, not local authentication.

### "No active range found."

You need to launch a range from the Shifter portal before using MCP tools.

### "Cannot connect to MCP server."

The mcp-shifter service may be down or unreachable. Check:
- mcp-shifter container is running
- Network connectivity between OpenWebUI and mcp-shifter
- Valve configuration has correct URL

### "Session limit reached."

Too many active sessions. Close unused browser tabs or wait for sessions to expire (5 minute idle timeout).

### "MCP server did not return session ID"

The mcp-shifter server responded but didn't include the `mcp-session-id` header. This indicates a server-side issue.
