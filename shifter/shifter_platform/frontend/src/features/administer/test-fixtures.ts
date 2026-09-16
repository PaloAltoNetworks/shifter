import type { AdminUserDetail, AuditLog } from "@/api/types";

/** Build an AdminUserDetail-shaped fixture for Administer page tests. */
export function adminUser(overrides: Partial<AdminUserDetail> = {}): AdminUserDetail {
  return {
    id: 1,
    username: "alice",
    email: "alice@example.com",
    display_name: "Alice Example",
    is_active: true,
    is_staff: false,
    is_superuser: false,
    user_type: "standard",
    account_origin: "local",
    is_ctf_organizer: false,
    is_deleted: false,
    date_joined: "2026-01-01T00:00:00Z",
    last_login: null,
    organizer_grant_source: "",
    must_change_password: false,
    groups: [],
    lifecycle_state: "active",
    available_actions: [],
    ...overrides,
  };
}

/** Build an AuditLog-shaped fixture for audit-history page tests. */
export function auditEvent(overrides: Partial<AuditLog> = {}): AuditLog {
  return {
    id: 1,
    entity_type: "workspace_membership",
    entity_id: 42,
    action: "role_sync",
    actor_type: "user",
    actor_id: 5,
    timestamp: "2026-08-01T12:00:00Z",
    previous_state: null,
    new_state: null,
    context: "",
    source_ip: null,
    user_agent: "",
    request_id: "",
    ...overrides,
  };
}

/** Wrap results in the DRF paginated-list envelope the list hook returns. */
export function pageOf<T>(results: T[]): { count: number; next: null; previous: null; results: T[] } {
  return { count: results.length, next: null, previous: null, results };
}
