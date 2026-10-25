import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { apiFetch } from "@/api/client";
import { renderRoute } from "@/test/utils";
import { RangeModelSources } from "./RangeModelSources";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));
const api = vi.mocked(apiFetch);
beforeEach(() => { api.mockReset(); });

it("applies the displayed revision and makes blocked replacement visible", async () => {
  const policy = { request_id: "range-1", workspace: "workspace-1", scenario: "synthetic", revision: 4,
    selection: { aliases: [] }, error: "", runtime: { state: "active", assignments: [] } };
  api.mockImplementation(async (url, options) => {
    if (url.includes("model-ranges")) return { count: 1, page: 1, has_next: false,
      results: [{ request_id: "range-1", scenario: "synthetic", revision: 4, status: "ready", error: "" }] };
    if (url.includes("model-source-options")) return { available: true, workspace: "workspace-1", workspaces: [], aliases: [] };
    return options?.method === "PUT" ? { ...policy, revision: 5, error: "source.admission_unavailable", runtime: { state: "unavailable", assignments: [] } } : policy;
  });
  renderRoute(<RangeModelSources organization="org-1" />);
  fireEvent.click(await screen.findByRole("button", { name: "Manage model sources" }));
  fireEvent.click(await screen.findByRole("button", { name: "Apply source policy" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/cms/ranges/range-1/model-sources/", {
    method: "PUT", body: { expected_revision: 4, selection: { aliases: [] } },
  }));
  expect(await screen.findByText(/The old grant remains revoked/)).toBeInTheDocument();
  expect(screen.getByText("Model access is unavailable.")).toBeInTheDocument();
});

it("revokes a range's model access through the revoke endpoint", async () => {
  const policy = { request_id: "range-1", workspace: "workspace-1", scenario: "synthetic", revision: 4,
    selection: { aliases: [] }, error: "", runtime: { state: "active", assignments: [] } };
  api.mockImplementation(async (url) => {
    if (url.includes("model-ranges")) return { count: 1, page: 1, has_next: false,
      results: [{ request_id: "range-1", scenario: "synthetic", revision: 4, status: "ready", error: "" }] };
    if (url.includes("model-source-options")) return { available: true, workspace: "workspace-1", workspaces: [], aliases: [] };
    if (url.includes("/revoke/")) return { ...policy, runtime: { state: "unavailable", assignments: [] } };
    return policy;
  });
  renderRoute(<RangeModelSources organization="org-1" />);
  fireEvent.click(await screen.findByRole("button", { name: "Manage model sources" }));
  fireEvent.click(await screen.findByRole("button", { name: "Revoke model access" }));
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith("/cms/ranges/range-1/model-sources/revoke/", { method: "POST", body: {} }));
});
