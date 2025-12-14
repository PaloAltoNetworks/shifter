# Feature Specification: Risk Register

**Feature Branch**: `001-risk-register`
**Created**: 2025-12-13
**Status**: Draft
**Input**: User description: "Risk register web app with UI for viewing risks with descriptions and threat modeling, comments, close/delete actions. Django app in existing portal. Full API control with API key auth. Two user types: admins and AI agents."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - View and Browse Risks (Priority: P1)

As an administrator or AI agent, I need to view all risks in the register so I can understand
the current risk landscape and prioritize remediation efforts.

**Why this priority**: Without the ability to view risks, no other functionality matters. This is
the foundation that enables all risk management workflows.

**Independent Test**: Can be fully tested by creating sample risks and verifying they appear in
both the UI (for humans) and API response (for AI agents). Delivers immediate value as a read-only
risk dashboard.

**Acceptance Scenarios**:

1. **Given** risks exist in the register, **When** an admin accesses the risk list page, **Then**
   they see all risks with title, severity, status, and last updated date
2. **Given** risks exist in the register, **When** an AI agent calls the list risks endpoint with
   a valid API key, **Then** they receive a JSON array of all risks with complete details
3. **Given** a specific risk exists, **When** a user views the risk detail, **Then** they see
   full description, threat modeling data (STRIDE category, likelihood, impact), affected assets,
   and mitigation status
4. **Given** many risks exist, **When** a user filters by status or severity, **Then** only
   matching risks are displayed

---

### User Story 2 - Create and Update Risks (Priority: P2)

As an administrator or AI agent, I need to create new risks and update existing ones so the
register stays current as threats are identified and situations change.

**Why this priority**: After viewing, the ability to populate and maintain the register is the
next essential capability. Without this, the register becomes stale.

**Independent Test**: Can be tested by creating a risk through UI, verifying it appears, then
updating it via API and confirming changes persist. Delivers value as a complete risk capture system.

**Acceptance Scenarios**:

1. **Given** I am authenticated, **When** I submit a new risk with required fields (title,
   description, severity, STRIDE category), **Then** the risk is created and visible in the list
2. **Given** a risk exists, **When** I update its severity or status, **Then** the change is
   persisted and the audit trail records who made the change and when
3. **Given** I am creating a risk, **When** I specify threat modeling data (likelihood score,
   impact score, attack vector), **Then** all threat data is stored and retrievable
4. **Given** an AI agent has a valid API key, **When** it creates a risk via POST request,
   **Then** the risk is created with the API key identity recorded in the audit trail

---

### User Story 3 - Comment on Risks (Priority: P3)

As an administrator or AI agent, I need to add comments to risks so discussions, updates, and
context are captured alongside the risk record.

**Why this priority**: Comments enable collaboration and historical context, but the register
provides value even without them. This extends the core functionality.

**Independent Test**: Can be tested by adding comments to a risk and verifying they appear in
chronological order. Delivers value as a discussion thread attached to each risk.

**Acceptance Scenarios**:

1. **Given** a risk exists, **When** I add a comment, **Then** the comment appears on the risk
   detail with author and timestamp
2. **Given** a risk has comments, **When** I view the risk, **Then** comments display in
   chronological order (oldest first)
3. **Given** an AI agent adds a comment via API, **Then** the comment shows the API key identity
   as the author
4. **Given** a comment exists, **When** I attempt to edit it, **Then** the system creates a new
   comment version rather than modifying the original (immutable comments)

---

### User Story 4 - Close and Delete Risks (Priority: P4)

As an administrator or AI agent, I need to close resolved risks and delete irrelevant ones so
the register reflects current actionable items.

**Why this priority**: Lifecycle management is important but secondary to viewing, creating, and
discussing risks. A register with only open risks still provides value.

**Independent Test**: Can be tested by closing a risk and verifying its status changes, then
soft-deleting a risk and confirming it no longer appears in default views.

**Acceptance Scenarios**:

1. **Given** a risk is open, **When** I close it with a resolution reason, **Then** its status
   changes to "closed" and the closure is recorded in the audit trail
2. **Given** a risk exists, **When** I delete it, **Then** it is soft-deleted (hidden from
   default views but retained in database)
3. **Given** I have appropriate permissions, **When** I view deleted risks, **Then** I can see
   previously deleted items and optionally restore them
4. **Given** a risk has been closed, **When** I reopen it, **Then** it returns to "open" status
   with the reopening recorded in the audit trail

---

### User Story 5 - API Key Management (Priority: P5)

As an administrator, I need to create and manage API keys so AI agents can access the risk
register programmatically.

**Why this priority**: While essential for AI agent access, human admins can use the UI without
API keys. This is infrastructure that enables the dual-actor model.

**Independent Test**: Can be tested by creating an API key, using it to make an API call, then
revoking it and confirming subsequent calls fail.

**Acceptance Scenarios**:

1. **Given** I am an admin, **When** I create a new API key, **Then** the key is generated with
   a visible value shown once (never shown again after creation)
2. **Given** an API key exists, **When** it is used in an API request, **Then** the request is
   authenticated and the key identity is available for audit logging
3. **Given** an API key exists, **When** I revoke it, **Then** all subsequent API calls using
   that key are rejected
4. **Given** I am managing API keys, **When** I view the key list, **Then** I see key prefix,
   creation date, last used date, and status (active/revoked)

---

### Edge Cases

- What happens when a user tries to view a risk that has been deleted?
  - System returns 404 for API, redirects to list with message for UI
- What happens when an API request uses an invalid or expired API key?
  - System returns 401 Unauthorized with clear error message
- What happens when required fields are missing during risk creation?
  - System returns 400 Bad Request with field-specific validation errors
- What happens when a risk has no threat modeling data?
  - Risk is still valid; threat modeling fields are optional but encouraged
- What happens when two users update the same risk simultaneously?
  - Last write wins; audit trail shows both updates

## Requirements *(mandatory)*

### Functional Requirements

**Risk Management**
- **FR-001**: System MUST allow authenticated users to create risks with: title, description,
  severity (critical/high/medium/low), and status (open/acknowledged/mitigating/resolved/closed)
- **FR-002**: System MUST support threat modeling fields on risks: STRIDE category, likelihood
  score (1-5), impact score (1-5), attack vector description, and affected assets
- **FR-003**: System MUST allow risks to be updated by authenticated users with changes recorded
  in an audit trail
- **FR-004**: System MUST support soft-deletion of risks (marked deleted, not physically removed)
- **FR-005**: System MUST provide list and detail views for risks with filtering by status and
  severity

**Comments**
- **FR-006**: System MUST allow authenticated users to add comments to risks
- **FR-007**: Comments MUST be immutable once created (edits create new versions)
- **FR-008**: Comments MUST display with author identification and timestamp

**Authentication & Authorization**
- **FR-009**: Web UI MUST authenticate users via existing Cognito OIDC integration
- **FR-010**: API MUST authenticate requests via API key passed in request header
- **FR-011**: API keys MUST be manageable through an admin interface (create, view, revoke)
- **FR-012**: API keys MUST be stored as hashed values, never in plaintext
- **FR-013**: All endpoints MUST require authentication (no anonymous access)

**Audit Trail**
- **FR-014**: System MUST record all state changes with: actor identity, timestamp, previous
  value, new value
- **FR-015**: Audit trail MUST distinguish between human users and API key actors

**API**
- **FR-016**: All CRUD operations MUST be available via REST API endpoints
- **FR-017**: API MUST accept and return JSON payloads
- **FR-018**: API errors MUST return structured JSON with error code and message

### Key Entities

- **Risk**: The central entity representing a security risk. Contains title, description,
  severity, status, threat modeling data, creation/update timestamps, and soft-delete flag.
  Owned by the system (not user-specific). Related to Comments and AuditLog entries.

- **Comment**: A timestamped note attached to a Risk. Contains text content, author reference,
  creation timestamp. Immutable once created. References parent comment if it's an edit/version.

- **APIKey**: Credential for programmatic access. Contains hashed key value, visible prefix for
  identification, associated name/description, creation timestamp, optional expiry, revocation
  status. Used for authentication and audit attribution.

- **AuditLog**: Record of a state change. Contains target entity type and ID, action type
  (create/update/delete/close/reopen), actor reference (user or API key), timestamp, previous
  and new values as structured data.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Authenticated users can create a new risk with threat modeling data in under
  2 minutes using the web UI
- **SC-002**: AI agents can perform all CRUD operations on risks using only the API (no UI
  required for any operation)
- **SC-003**: Risk list page loads and displays up to 100 risks within 2 seconds
- **SC-004**: All state changes (create, update, delete, close) have corresponding audit trail
  entries with 100% coverage
- **SC-005**: API key authentication adds less than 50ms overhead to request processing
- **SC-006**: Administrators can create, view, and revoke API keys without developer assistance
- **SC-007**: Comments on risks are displayed in correct chronological order with author
  attribution
- **SC-008**: Deleted risks do not appear in default list views but remain queryable by admins

## Assumptions

- Existing Cognito OIDC authentication in the portal will be reused for web UI access
- The portal's existing user model will be extended or referenced for user attribution
- API versioning will use URL prefix pattern (`/api/v1/`)
- Default severity for unspecified risks is "medium"
- Default status for new risks is "open"
- Likelihood and impact scores use 1-5 scale (1=lowest, 5=highest)
- STRIDE categories are: Spoofing, Tampering, Repudiation, Information Disclosure, Denial of
  Service, Elevation of Privilege
- Rate limiting for API access is not required for initial implementation
- Pagination will be implemented for list endpoints (default 50 items per page)
