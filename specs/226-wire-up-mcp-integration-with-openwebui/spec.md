# Feature Specification: MCP Integration with OpenWebUI

**Feature Branch**: `226-wire-up-mcp-integration-with-openwebui`
**Created**: 2025-12-14
**Status**: Draft
**Input**: User description: "Wire up MCP integration with OpenWebUI to enable AI-driven control of user-specific Kali instances"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - User Accesses Chat with Single Sign-On (Priority: P1)

A PANW domain consultant authenticated to the Portal clicks "Open Range" and is seamlessly authenticated to the Chat UI without re-entering credentials. The Chat UI recognizes their identity for subsequent MCP operations.

**Why this priority**: Authentication is the foundation. Without unified identity, we cannot route MCP commands to user-specific Kali instances.

**Independent Test**: Can be tested by verifying a Portal-authenticated user can access the chat subdomain (`chat.{domain}`) without login prompts, and the system can identify their email from the session.

**Acceptance Scenarios**:

1. **Given** a user is authenticated to Portal via Cognito, **When** they navigate to the Chat UI, **Then** they are automatically authenticated without a login prompt.
2. **Given** an unauthenticated user navigates to the Chat UI directly, **When** the page loads, **Then** they are redirected to Cognito login.
3. **Given** a user's session has expired, **When** they access the Chat UI, **Then** they are prompted to re-authenticate.

---

### User Story 2 - User Chats and AI Executes on Their Kali Instance (Priority: P1)

A consultant with a provisioned range chats naturally ("scan the target for open ports", "check what's running"). The AI agent uses MCP tools to execute commands on that user's specific Kali instance - never another user's.

**Why this priority**: This is the core value proposition. The existing SSH/session management works; we need to route it to the correct target per-user based on their identity.

**Independent Test**: Can be tested by having User A and User B each with active ranges ask "run whoami" via chat, and verify each sees output from their own Kali instance (different IPs).

**Acceptance Scenarios**:

1. **Given** a user with an active range (status='ready'), **When** they chat and the AI invokes MCP tools, **Then** commands execute on their Kali IP (from their range record).
2. **Given** a user with no active range, **When** they try to chat, **Then** they receive feedback that no range is available and should launch one from the Portal.
3. **Given** two users with different active ranges chatting concurrently, **When** each AI invokes MCP tools, **Then** each routes to the correct user's Kali instance.

---

### User Story 3 - Portal Sets Chat URL on Range Ready (Priority: P2)

When the provisioning workflow completes and a range becomes ready, the system sets the `chat_url` field so the Portal can display "Open Range" linking to the Chat UI.

**Why this priority**: Connects the provisioning pipeline to the chat experience. Depends on Stories 1 and 2 working.

**Independent Test**: Can be tested by launching a range and verifying the `chat_url` field is populated when status transitions to 'ready'.

**Acceptance Scenarios**:

1. **Given** a range is being provisioned, **When** the `mark_ready` step completes, **Then** the range record has a valid `chat_url`.
2. **Given** a range is in 'ready' status with a `chat_url`, **When** the user views the Portal dashboard, **Then** "Open Range" links to that URL.

---

### User Story 4 - AI Agent Manages Sessions Transparently (Priority: P2)

A consultant chats naturally ("run msfconsole and set up a handler"). The AI agent autonomously creates and manages persistent sessions as needed to accomplish multi-step tasks. The user doesn't directly manage sessions - they just describe what they want done.

**Why this priority**: Complex attack scenarios require the agent to maintain state across tool calls. The existing session management works; we need it to function through HTTP transport.

**Independent Test**: Can be tested by asking the agent to "start msfconsole, set up a reverse TCP handler on port 4444, then background it" and verifying the agent creates appropriate sessions and the handler persists.

**Acceptance Scenarios**:

1. **Given** a user asks the AI to run a long-running tool (e.g., msfconsole), **When** the AI invokes session tools, **Then** the session persists across subsequent chat messages.
2. **Given** the AI has created sessions during a conversation, **When** the user asks to "clean up" or the AI detects orphaned sessions, **Then** sessions can be closed.
3. **Given** the AI forgets to close sessions, **When** the session timeout expires, **Then** sessions are automatically cleaned up.

---

### Edge Cases

- What happens when MCP cannot SSH to the Kali instance (e.g., instance terminated)? AI receives error, explains to user; event is logged.
- What happens when the Cognito token expires mid-chat? User must re-authenticate.
- What happens when the database is temporarily unavailable? MCP returns a service unavailable error; retries on next request.
- What happens when the AI creates sessions but forgets to clean them up? Sessions auto-expire after timeout (from config file); user can also ask "clean up sessions".
- What happens when AI hits per-user session limit? AI receives error with list of active sessions and instructions to close unused ones; AI should use `kali_close_session` or `kali_close_all_sessions`.
- What happens when global session limit is reached? AI receives error indicating system at capacity; user should try again later.

**Note**: Users are limited to one active range at a time (enforced by provisioner per issue #144).

## Requirements *(mandatory)*

### Functional Requirements

#### Transport Layer Adaptation

- **FR-001**: MCP server MUST expose an HTTP-based transport endpoint compatible with OpenWebUI's MCP integration (Streamable HTTP or SSE)
- **FR-002**: MCP server MUST extract user identity from Cognito JWT in the Authorization header
- **FR-003**: MCP server MUST validate JWT tokens before processing requests
- **FR-004**: HTTP transport MUST support streaming responses for long-running commands

#### Dynamic Range Resolution

- **FR-005**: MCP server MUST query the database to find the active range for the authenticated user (by email)
- **FR-006**: MCP server MUST retrieve SSH credentials (private key) from Secrets Manager using the ARN stored in the range record
- **FR-007**: MCP server MUST construct a dynamic `LabConfig` per-request with the user's Kali IP, SSH key, and connection details
- **FR-008**: The dynamic config MUST be passed to existing `aptl-mcp-common` handlers via `ToolContext`

#### Existing Functionality Preservation

- **FR-009**: All existing MCP tools (`kali_run_command`, `kali_interactive_session`, `kali_session_command`, etc.) MUST work unchanged
- **FR-010**: `SSHConnectionManager` session caching MUST continue to work (connection pooling by `{user}@{host}:{port}`)
- **FR-011**: `PersistentSession` lifecycle (keep-alive, timeout, background buffering) MUST work unchanged

#### Infrastructure Routing

- **FR-012**: Load balancer MUST route requests for `chat.{domain}` subdomain to the AgentChat host
- **FR-013**: AgentChat host MUST have network path to Kali instances in the Range VPC (via VPC peering or similar)
- **FR-014**: AgentChat host MUST have access to the RDS database for range lookups
- **FR-015**: AgentChat host MUST have IAM permissions to read from Secrets Manager

#### Authentication Infrastructure

- **FR-016**: Cognito user pool MUST have a separate app client configured for OpenWebUI with appropriate callback URLs
- **FR-017**: OpenWebUI MUST be configured with Cognito OIDC settings (provider URL, client ID, client secret, scopes)

#### Provisioning Integration

- **FR-018**: Provisioning workflow MUST store SSH private key in Secrets Manager and record the ARN in the range record
- **FR-019**: Provisioning workflow MUST set `chat_url` field when range reaches 'ready' status

#### Resource Management

- **FR-020**: MCP server MUST enforce a per-user session limit (value from config, no default)
- **FR-021**: MCP server MUST enforce a global max sessions limit (value from config, no default)
- **FR-022**: MCP server MUST log INFO when global sessions reach threshold (value from config, no default)
- **FR-023**: MCP server MUST log WARN when global sessions reach threshold (value from config, no default)
- **FR-024**: MCP server MUST close idle SSH connections (zero active sessions) after timeout (value from config, no default)
- **FR-025**: MCP server MUST fail to start if any required config value is missing (no hardcoded defaults)
- **FR-026**: When session limit is reached, MCP server MUST return clear error message to AI agent indicating limit reached and suggesting session cleanup

### Key Entities

- **Range**: User's provisioned environment; contains `kali_ip`, `kali_ssh_key_secret_arn`, `status`, `chat_url`; linked to user via `user_id`
- **LabConfig (dynamic)**: Per-request configuration constructed from range lookup; contains SSH target, credentials, server metadata; passed to existing handlers
- **SSHConnectionManager**: Existing component; manages connection pool and persistent sessions; unchanged
- **MCP HTTP Wrapper**: New thin layer; handles HTTP transport, JWT extraction, range lookup; delegates to existing `createMCPServer` logic

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Authenticated users can invoke MCP tools within 5 seconds of sending a chat message
- **SC-002**: 100% of MCP tool invocations route to the correct user's Kali instance (no cross-user access)
- **SC-003**: Existing SSH command execution and session management capabilities remain fully functional
- **SC-004**: Users with no active range receive clear error feedback within 2 seconds
- **SC-005**: Persistent sessions maintain state across multiple HTTP requests within timeout period
- **SC-006**: All authentication and MCP invocation events are logged with user identity for audit

## Assumptions

- OpenWebUI v0.6.41 supports MCP server integration via HTTP transport
- Existing `aptl-mcp-common` SSH and session logic is production-ready and unchanged
- Cognito user pool and Portal authentication already exist
- Range table includes `kali_ip`, `kali_ssh_key_secret_arn`, `chat_url`, and `status` fields
- VPC peering between Portal VPC and Range VPC is feasible
- SSH keys are generated per-range during provisioning and stored in Secrets Manager

## Dependencies

- OpenWebUI v0.6.41 with MCP support
- MCP SDK `@modelcontextprotocol/sdk` with HTTP transport capability
- Existing `aptl-mcp-common` library (unchanged)
- Existing Portal ALB and Cognito infrastructure
- Existing RDS database with Range model
- AWS Secrets Manager for SSH key storage
