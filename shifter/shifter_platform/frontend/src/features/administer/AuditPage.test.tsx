import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import { axe } from "vitest-axe";

import { ApiError } from "@/api/errors";
import { renderRoute, setupUser } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { auditEvent, pageOf } from "./test-fixtures";
import { AuditPage } from "./AuditPage";

const mockApi = vi.mocked(apiFetch);

const AUDIT_PATH = "/administer/audit";

function renderAudit(initialEntry = AUDIT_PATH) {
  return renderRoute(<AuditPage />, { path: AUDIT_PATH, initialEntries: [initialEntry] });
}

/** The query object apiFetch received on its Nth call (default: first). */
function queryOf(call = 0): Record<string, unknown> {
  return (mockApi.mock.calls[call][1] as { query: Record<string, unknown> }).query;
}

beforeEach(() => {
  mockApi.mockReset();
});

describe("AuditPage", () => {
  it("renders loaded audit events with action, entity, and actor", async () => {
    mockApi.mockResolvedValue(pageOf([auditEvent()]));
    renderAudit();

    const table = await screen.findByRole("table");
    expect(within(table).getByText("role_sync")).toBeInTheDocument();
    expect(within(table).getByText("workspace_membership #42")).toBeInTheDocument();
    expect(within(table).getByText("user #5")).toBeInTheDocument();
  });

  it("reads the canonical global audit endpoint with no workspace scope", async () => {
    mockApi.mockResolvedValue(pageOf([auditEvent()]));
    renderAudit();
    await screen.findByRole("table");

    expect(mockApi.mock.calls[0][0]).toBe("/audit/");
    // The audit feed is deployment-global: no workspace UUID may filter it.
    expect(JSON.stringify(mockApi.mock.calls[0])).not.toMatch(/workspace/i);
  });

  it("maps URL filter params onto the typed API query", async () => {
    mockApi.mockResolvedValue(pageOf([]));
    renderAudit(`${AUDIT_PATH}?action=role_sync&entity_type=workspace_membership&actor_id=5&page=2`);
    await screen.findByText("No events match these filters");

    const query = queryOf();
    expect(query.action).toBe("role_sync");
    expect(query.entity_type).toBe("workspace_membership");
    expect(query.actor_id).toBe("5");
    expect(query.page).toBe(2);
  });

  it.each([
    ["actor_id", "actor_id"],
    ["entity_id", "entity_id"],
  ])("sends a malformed %s to the server instead of dropping the filter", async (_label, param) => {
    // A malformed id must not silently broaden the result; it reaches the server,
    // which validates it and returns 400 that the page surfaces as invalid.
    mockApi.mockRejectedValue(new ApiError(400, { code: "invalid", message: "bad" }));
    renderAudit(`${AUDIT_PATH}?${param}=not-an-int`);

    expect(await screen.findByText("Those filters are not valid")).toBeInTheDocument();
    expect(queryOf()[param]).toBe("not-an-int");
  });

  it("applies filters through the form and reflects them in the URL and refetch", async () => {
    const user = setupUser();
    mockApi.mockResolvedValue(pageOf([]));
    renderAudit();
    await screen.findByText("No audit events yet");

    await user.type(screen.getByLabelText("Event type (action)"), "login_failed");
    await user.click(screen.getByRole("button", { name: "Apply filters" }));

    await waitFor(() => {
      expect(mockApi.mock.calls.some((call) => (call[1] as { query: { action?: string } }).query.action === "login_failed")).toBe(true);
    });
  });

  it("distinguishes the initial empty state", async () => {
    mockApi.mockResolvedValue(pageOf([]));
    renderAudit();
    expect(await screen.findByText("No audit events yet")).toBeInTheDocument();
  });

  it("renders a permission-denied state on 403", async () => {
    mockApi.mockRejectedValue(new ApiError(403, { code: "forbidden", message: "no" }));
    renderAudit();
    expect(await screen.findByText("You do not have permission to view audit events")).toBeInTheDocument();
  });

  it("renders an invalid-filters state on 400", async () => {
    mockApi.mockRejectedValue(new ApiError(400, { code: "invalid", message: "bad" }));
    renderAudit(`${AUDIT_PATH}?from=2026-08-02T00:00&to=2026-08-01T00:00`);
    expect(await screen.findByText("Those filters are not valid")).toBeInTheDocument();
  });

  it("renders a generic error state on failure", async () => {
    mockApi.mockRejectedValue(new ApiError(500, { code: "error", message: "boom" }));
    renderAudit();
    expect(await screen.findByText("Could not load audit events")).toBeInTheDocument();
  });

  it("shows sensitive evidence only inside an explicit escaped detail disclosure", async () => {
    mockApi.mockResolvedValue(
      pageOf([
        auditEvent({
          context: "changed role to admin",
          source_ip: "203.0.113.7",
          new_state: { role: "admin" },
        }),
      ]),
    );
    const user = setupUser();
    renderAudit();
    await screen.findByRole("table");

    // Sensitive evidence is not shown until the disclosure is opened.
    expect(screen.queryByText("203.0.113.7")).not.toBeInTheDocument();
    await user.click(screen.getByText("View details"));
    expect(screen.getByText("203.0.113.7")).toBeInTheDocument();
    expect(screen.getByText("changed role to admin")).toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue(pageOf([auditEvent()]));
    const { container } = renderAudit();
    await screen.findByRole("table");
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});
