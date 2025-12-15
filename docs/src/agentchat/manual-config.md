# OpenWebUI Manual Configuration

Manual admin panel settings required after deployment. These should be automated in a future iteration.

## Admin Panel Settings

### Models

**Path:** Admin Panel → Settings → Models

| Setting | Value | Reason |
|---------|-------|--------|
| Disable unwanted models | Hide all except approved | Only show Claude Sonnet 4.5, DeepSeek v3 |

### Interface

**Path:** Admin Panel → Settings → Interface

| Setting | Value | Reason |
|---------|-------|--------|
| Enable New Chat Suggestions | Off | Not needed for our use case |
| Enable Chat Suggestions | Off | Not needed for our use case |
| Show Suggested Users | Off / Delete | Remove default suggestions |

---

## MCP Wrapper Tool

The MCP wrapper enables AI-driven pentesting by forwarding user OAuth tokens to mcp-shifter.

### Installation

**Path:** Workspace → Tools → + (Create Tool)

1. Copy the contents of `mcp/openwebui-mcp-wrapper/mcp_wrapper.py`
2. Paste into the tool editor
3. Click **Save**
4. Set visibility to "Public" to make available to all users

### Valve Configuration

No configuration needed. The defaults match our docker-compose deployment.

### Verification

After installation, test with a chat prompt:

```
What MCP tools do you have available?
```

The AI should list available tools (e.g., `run_command`, `file_read`, `file_write`).

### Troubleshooting

| Error | Cause | Solution |
|-------|-------|----------|
| "Not authenticated" | OAuth token not available | Log in via Cognito SSO, not local auth |
| "No active range" | User has no range in "ready" status | Launch a range from the Portal |
| "Cannot connect to MCP server" | mcp-shifter not running | Check container status: `docker ps` |
| "Session limit reached" | Too many sessions | Close unused tabs, wait for 5min timeout |

---

## Future Automation

These settings are stored in OpenWebUI's SQLite database (`/app/backend/data/webui.db`). Potential automation approaches:

1. **Pre-configured volume**: Snapshot configured DB, mount on deploy
2. **SQL seed script**: Run SQL updates via SSM after container start
3. **OpenWebUI API**: Use admin API endpoints if available
4. **Environment variables**: Check if OWUI supports config via env vars

Track automation work in GitHub issues.
