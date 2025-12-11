# API Reference

## MCP Tools

### victim_run_command

Execute command on victim instance.

**Parameters:**
- `command` (string): Command to execute
- `timeout_seconds` (number, optional): Timeout in seconds

**Returns:** Command output

### victim_interactive_session

Create persistent SSH session to victim.

**Parameters:**
- `session_name` (string): Identifier for session

**Returns:** Session ID

### list_sessions

List active SSH sessions.

**Returns:** Array of session info

### close_session

Close SSH session.

**Parameters:**
- `session_id` (string): Session to close

### get_session_output

Retrieve output from session.

**Parameters:**
- `session_id` (string): Session ID
- `timeout_ms` (number, optional): Wait timeout

**Returns:** Accumulated output
