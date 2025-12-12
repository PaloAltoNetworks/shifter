# API Reference

## Portal REST API

### Range Management

#### GET /mission-control/api/range/status/

Get current user's active range.

**Response**:
```json
{
  "has_range": true,
  "range": {
    "id": 42,
    "status": "ready",
    "agent_id": 7,
    "agent_name": "Cortex XDR",
    "chat_url": "https://...",
    "error_message": null,
    "created_at": "2025-12-11T12:00:00Z",
    "ready_at": "2025-12-11T12:05:00Z",
    "paused_at": null
  }
}
```

#### POST /mission-control/api/range/launch/

Launch new range.

**Request**:
```json
{"agent_id": 7}
```

**Response**: Same as status, with `success: true`.

**Errors**:
- 409: Active range already exists
- 404: Agent not found
- 503: No capacity (max 254 concurrent ranges)

#### POST /mission-control/api/range/destroy/

Destroy active/paused/failed range.

**Response**: `{"success": true, "range": {...}}`

#### POST /mission-control/api/range/cancel/

Cancel provisioning range (PENDING/PROVISIONING only).

**Response**: `{"success": true}`

### Agent Management

#### GET /mission-control/api/agents/

List user's agents.

**Response**:
```json
{
  "agents": [
    {"id": 7, "name": "Cortex XDR", "os_name": "Windows", "file_size_mb": 150.3}
  ]
}
```

#### POST /mission-control/api/upload/initiate/

Request presigned S3 URL.

**Request**:
```json
{"name": "My Agent", "filename": "agent.msi", "file_size": 157286400}
```

**Response**:
```json
{
  "presigned_url": "https://s3...?X-Amz-...",
  "s3_key": "agents/42/abc123_agent.msi",
  "upload_token": "eyJ...",
  "expected_os": "windows"
}
```

**Errors**:
- 400: Invalid size, unsupported extension
- 409: Upload already in progress
- 413: Exceeds quota

#### POST /mission-control/api/upload/complete/

Finalize upload after S3 PUT.

**Request**:
```json
{"upload_token": "eyJ...", "sha256_hash": "abc..."}
```

**Response**:
```json
{"success": true, "agent_id": 8, "message": "Agent 'My Agent' uploaded successfully."}
```

**Errors**:
- 400: File not found in S3, invalid token
- 403: Token user mismatch

#### POST /mission-control/api/upload/cancel/

Cancel in-progress upload (cleans up S3).

**Request**: `{"upload_token": "eyJ..."}`

**Response**: `{"success": true}`

**Note**: CSRF exempt to support `navigator.sendBeacon()`. Auth via `@login_required` + HMAC-signed token.

## MCP Tools

LibreChat MCP servers provide SSH access to victim VM.

### victim_run_command

Execute command on victim.

**Params**: `command` (string), `timeout_seconds` (number, optional)

**Returns**: Command output (stdout + stderr)

### victim_interactive_session

Create persistent SSH session.

**Params**: `session_name` (string)

**Returns**: `session_id` (string)

### victim_send_input

Send input to session.

**Params**: `session_id` (string), `input` (string)

### victim_get_output

Read session output.

**Params**: `session_id` (string), `timeout_ms` (number, optional)

**Returns**: Accumulated output since last read

### victim_close_session

Close session.

**Params**: `session_id` (string)

### list_sessions

List active sessions.

**Returns**: Array of `{session_id, session_name, created_at}`

### victim_upload_file

Upload file to victim.

**Params**: `local_path` (string), `remote_path` (string)

### victim_download_file

Download file from victim.

**Params**: `remote_path` (string), `local_path` (string)

**Note**: Tools are namespaced with `victim_` prefix (configurable via MCP `toolPrefix`).
