# Tasks: MCP Integration with OpenWebUI

**Input**: Design documents from `/specs/226-wire-up-mcp-integration-with-openwebui/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Not explicitly requested - test tasks omitted.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

Based on plan.md structure:
- **MCP Server**: `mcp/mcp-shifter/src/`
- **Django Portal**: `portal/mission_control/`
- **Terraform**: `terraform/modules/`
- **Provisioner**: `terraform/modules/range/provisioner/lambda/`

---

## Phase 1: Setup (Project Initialization)

**Purpose**: Create mcp-shifter package structure and install dependencies

- [X] T001 Create mcp-shifter package directory structure in mcp/mcp-shifter/
- [X] T002 Initialize package.json with dependencies (express, aws-jwt-verify, @aws-sdk/rds-signer, @aws-sdk/client-secrets-manager, pg, aptl-mcp-common, zod) in mcp/mcp-shifter/package.json
- [X] T003 [P] Create tsconfig.json for TypeScript compilation in mcp/mcp-shifter/tsconfig.json
- [X] T004 [P] Create config schema with Zod validation (sessions, connections settings) in mcp/mcp-shifter/src/config-schema.ts
- [X] T005 Create config loader that fails on missing values (no defaults) in mcp/mcp-shifter/src/config.ts

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before user stories

**Django Model Change**:
- [X] T006 Add kali_ssh_key_secret_arn field to Range model in portal/mission_control/models.py
- [X] T007 Create and run Django migration for new field

**Terraform Infrastructure**:
- [ ] T008 [P] Add Cognito app client for OpenWebUI in terraform/modules/portal/cognito.tf
- [ ] T009 [P] Add ALB target groups and listener rules for /chat and /mcp in terraform/modules/agentchat/alb.tf
- [ ] T010 [P] Add VPC peering between Portal VPC and Range VPC in terraform/modules/agentchat/vpc-peering.tf
- [ ] T011 [P] Add IAM policy for Secrets Manager and RDS access in terraform/modules/agentchat/iam.tf
- [ ] T012 [P] Add security group rules for SSH to Range VPC in terraform/modules/agentchat/security-groups.tf

**Provisioner Updates**:
- [X] T013 Update create_kali Lambda to generate SSH key pair in terraform/modules/range/provisioner/lambda/create_kali/
- [X] T014 Update create_kali Lambda to store private key in Secrets Manager in terraform/modules/range/provisioner/lambda/create_kali/
- [X] T015 Update create_kali Lambda to set kali_ssh_key_secret_arn in range record in terraform/modules/range/provisioner/lambda/create_kali/

**Checkpoint**: Infrastructure ready - MCP server implementation can begin

---

## Phase 3: User Story 1 - SSO Authentication (Priority: P1)

**Goal**: Portal-authenticated users access Chat UI without re-login; identity flows to MCP

**Independent Test**: User logged into Portal navigates to /chat, sees OpenWebUI without login prompt, and MCP can identify their email

### Implementation for User Story 1

- [X] T016 [P] [US1] Implement Cognito JWT verifier using aws-jwt-verify in mcp/mcp-shifter/src/auth.ts
- [X] T017 [P] [US1] Create Express middleware to extract and validate JWT from Authorization header in mcp/mcp-shifter/src/middleware/auth.ts
- [X] T018 [US1] Create user context type with email and claims in mcp/mcp-shifter/src/types.ts
- [X] T019 [US1] Add /health endpoint for ALB health checks in mcp/mcp-shifter/src/server.ts (inline)
- [ ] T020 [US1] Configure OpenWebUI OIDC settings in terraform (env vars) in terraform/modules/agentchat/openwebui.tf

**Checkpoint**: Users can access Chat UI via SSO; JWT validation works

---

## Phase 4: User Story 2 - Per-User Kali Routing (Priority: P1)

**Goal**: MCP commands execute on the authenticated user's Kali instance

**Independent Test**: User A and User B each run "whoami" and see output from their respective Kali IPs

### Implementation for User Story 2

**Database & Secrets Layer** (can run in parallel):
- [X] T021 [P] [US2] Implement RDS connection with IAM auth in mcp/mcp-shifter/src/db.ts
- [X] T022 [P] [US2] Implement range lookup query (by user email, status=ready) in mcp/mcp-shifter/src/db.ts (consolidated)
- [X] T023 [P] [US2] Implement Secrets Manager client for SSH key retrieval in mcp/mcp-shifter/src/secrets.ts

**Config & Session Layer** (depends on above):
- [X] T024 [US2] Create dynamic LabConfig builder from range data in mcp/mcp-shifter/src/lab-config-builder.ts
- [X] T025 [US2] Implement StreamableHTTPServerTransport setup in mcp/mcp-shifter/src/server.ts (inline)
- [X] T026 [US2] Create session manager with per-session LabConfig caching (Map<sessionId, {labConfig, transport, userEmail}>) in mcp/mcp-shifter/src/session-manager.ts

**HTTP Endpoints** (depends on session layer):
- [X] T027 [US2] Implement POST /mcp endpoint with session creation flow (JWT → range lookup → LabConfig → cache) in mcp/mcp-shifter/src/server.ts
- [~] T028 [US2] Implement GET /mcp endpoint for SSE notifications - handled internally by transport
- [X] T029 [US2] Implement DELETE /mcp endpoint for session termination in mcp/mcp-shifter/src/server.ts
- [X] T030 [US2] Add error response for "no active range" case in mcp/mcp-shifter/src/server.ts

**Server Entrypoint**:
- [X] T031 [US2] Create Express app entrypoint wiring routes, shared SSHConnectionManager, and generateToolHandlers in mcp/mcp-shifter/src/index.ts

**Checkpoint**: MCP tools execute on correct user's Kali; per-user isolation verified

---

## Phase 5: User Story 3 - Chat URL on Range Ready (Priority: P2)

**Goal**: Provisioner sets chat_url when range becomes ready

**Independent Test**: Launch a range, verify chat_url is populated when status=ready

### Implementation for User Story 3

- [X] T032 [US3] Update mark_ready Lambda to set chat_url field in terraform/modules/range/provisioner/lambda/mark_ready/
- [X] T033 [US3] Add chat_url to allowed_fields in provisioner shared/db.py in terraform/modules/range/provisioner/lambda/shared/db.py
- [X] T034 [US3] Verify Portal "Open Range" button uses chat_url (existing code check) in portal/mission_control/views.py

**Checkpoint**: Ranges ready for use have valid chat_url

---

## Phase 6: User Story 4 - Session Management (Priority: P2)

**Goal**: AI agent creates/manages sessions; resource limits enforced

**Independent Test**: Ask agent to run msfconsole in background, verify session persists; hit session limit and verify error message

### Implementation for User Story 4

**Session Limits** (can run in parallel):
- [X] T035 [P] [US4] Implement per-user session counter in session manager in mcp/mcp-shifter/src/session-manager.ts
- [X] T036 [P] [US4] Implement global session counter with INFO/WARN thresholds in mcp/mcp-shifter/src/session-manager.ts

**Limit Enforcement & Cleanup**:
- [X] T037 [US4] Add session limit error response with cleanup instructions in mcp/mcp-shifter/src/session-manager.ts
- [ ] T038 [US4] Implement idle connection cleanup timer (zero sessions after timeout) in mcp/mcp-shifter/src/connection-cleanup.ts
- [X] T039 [US4] Wire session limits from config (fail if missing) in mcp/mcp-shifter/src/session-manager.ts

**Logging**:
- [X] T040 [US4] Add structured logging for session create/close/limit events in mcp/mcp-shifter/src/logger.ts

**Checkpoint**: Session limits enforced; AI gets clear errors when limits reached

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Deployment, validation, documentation

- [X] T041 [P] Create Dockerfile for mcp-shifter in mcp/mcp-shifter/Dockerfile
- [X] T042 [P] Create example config.json with recommended values in mcp/mcp-shifter/config.example.json
- [ ] T043 Update AgentChat deployment workflow to include mcp-shifter in .github/workflows/agentchat.yml
- [ ] T044 Add MCP server to docker-compose for AgentChat in terraform/modules/agentchat/
- [ ] T045 Run quickstart.md validation (local dev test)
- [ ] T046 Verify end-to-end flow: Portal login → Chat UI → MCP command → Kali output

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies - start immediately
- **Phase 2 (Foundational)**: Depends on Setup - BLOCKS all user stories
- **Phase 3 (US1 - SSO)**: Depends on Foundational; can run in parallel with US3
- **Phase 4 (US2 - Routing)**: Depends on Foundational + US1 (needs JWT validation)
- **Phase 5 (US3 - Chat URL)**: Depends on Foundational only (independent of MCP server)
- **Phase 6 (US4 - Sessions)**: Depends on US2 (session manager must exist)
- **Phase 7 (Polish)**: Depends on all user stories complete

### User Story Dependencies

```
Foundational (Phase 2)
       │
       ├──────────────────┬───────────────────┐
       ▼                  ▼                   ▼
   US1 (SSO)          US3 (Chat URL)     [Can start]
       │                  │
       ▼                  │
   US2 (Routing)          │
       │                  │
       ▼                  ▼
   US4 (Sessions)     [Independent]
       │
       ▼
    Polish
```

### Parallel Opportunities

**Phase 2 (Foundational)**:
- T008, T009, T010, T011, T012 (Terraform files - different modules)

**Phase 3 (US1)**:
- T016, T017 (auth.ts vs middleware - different files)

**Phase 4 (US2)**:
- T021, T022, T023 (db.ts, range-lookup.ts, secrets.ts - independent)

**Phase 6 (US4)**:
- T035, T036 (per-user vs global counters - same file but different functions)

**Phase 7 (Polish)**:
- T041, T042 (Dockerfile vs config.example.json)

---

## Parallel Example: Phase 4 (User Story 2)

```bash
# Launch database/secrets layer together:
Task: "Implement RDS connection with IAM auth in mcp/mcp-shifter/src/db.ts"
Task: "Implement range lookup query in mcp/mcp-shifter/src/range-lookup.ts"
Task: "Implement Secrets Manager client in mcp/mcp-shifter/src/secrets.ts"

# Then sequentially:
Task: "Create dynamic LabConfig builder" (depends on range-lookup, secrets)
Task: "Implement StreamableHTTPServerTransport setup"
Task: "Create session manager with per-session LabConfig caching"
Task: "Implement POST/GET/DELETE /mcp endpoints" (depends on all above)
Task: "Create Express app entrypoint"
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (Terraform + Django migration)
3. Complete Phase 3: US1 (SSO working)
4. Complete Phase 4: US2 (Per-user routing working)
5. **STOP and VALIDATE**: Test with two users, verify isolation
6. Deploy to dev environment

### Incremental Delivery

1. Setup + Foundational → Infrastructure ready
2. Add US1 + US2 → Core MCP-OpenWebUI integration working (MVP!)
3. Add US3 → Provisioner integration complete
4. Add US4 → Resource management in place
5. Polish → Production-ready

---

## Architecture Notes

- **No createMCPServer**: Use aptl-mcp-common building blocks directly (SSHConnectionManager, generateToolHandlers)
- **Per-session LabConfig**: Built once on session creation, cached in session manager (no per-request DB/Secrets hits)
- **Shared SSHConnectionManager**: Single instance pools connections by `user@host:port` (natural per-user partitioning)
- **No hardcoded defaults**: All config values from config.json or server fails to start
- **Session metrics**: Deferred to issue #242
- **Audit logging**: Deferred to issue #243
- **File descriptor limits**: Raise on AgentChat EC2 (ulimit -n 65535)
