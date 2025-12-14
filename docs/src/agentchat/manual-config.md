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

## Future Automation

These settings are stored in OpenWebUI's SQLite database (`/app/backend/data/webui.db`). Potential automation approaches:

1. **Pre-configured volume**: Snapshot configured DB, mount on deploy
2. **SQL seed script**: Run SQL updates via SSM after container start
3. **OpenWebUI API**: Use admin API endpoints if available
4. **Environment variables**: Check if OWUI supports config via env vars

Track automation work in GitHub issues.
