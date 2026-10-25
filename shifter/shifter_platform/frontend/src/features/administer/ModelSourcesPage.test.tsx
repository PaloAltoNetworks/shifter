import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { apiFetch } from "@/api/client";
import { ApiError } from "@/api/errors";
import { renderRoute } from "@/test/utils";

import { ModelSourcesPage } from "./ModelSourcesPage";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));
const api = vi.mocked(apiFetch);
beforeEach(() => { api.mockReset(); });

it("allows tenant administrators to add a source from the tenant", async () => {
  api.mockImplementation(async (url) => url === "/workspaces/organizations/" ?
    { results: [{ uuid: "org-1", name: "Workshop" }] } : { results: [] });
  renderRoute(<ModelSourcesPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Add model source" }));
  expect(screen.getByLabelText("Provider")).toBeInTheDocument();
});

it("does not show credential controls on denied organization access", async () => {
  api.mockRejectedValue(new ApiError(403, { code: "denied", message: "Access denied" }));
  renderRoute(<ModelSourcesPage />);
  expect(await screen.findByText("Access denied")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Add model source" })).not.toBeInTheDocument();
});

it("retires unused credentials through the tenant and reports retained versions", async () => {
  const source = { id: "source-1", revision: 2, state: "ready", enabled: true,
    configuration: { name: "Workshop model", model: "synthetic", region: "provider-managed" } };
  api.mockImplementation(async (url) => {
    if (url === "/workspaces/organizations/") return { results: [{ uuid: "org-1", name: "Workshop" }] };
    if (url === "/cms/organizations/org-1/model-sources/") return { results: [source] };
    if (url.endsWith("retire-credentials/")) return { retired: 0 };
    return { results: [] };
  });
  renderRoute(<ModelSourcesPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Retire unused credentials for Workshop model" }));
  fireEvent.click(screen.getByRole("button", { name: "Retire unused credentials" }));
  expect(await screen.findByRole("status")).toHaveTextContent("No unused credentials are eligible yet");
  expect(api).toHaveBeenCalledWith("/cms/organizations/org-1/model-sources/source-1/retire-credentials/", {
    method: "POST", body: {},
  });
});
