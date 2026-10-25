import { screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { renderRoute, setupUser } from "@/test/utils";
vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));
import { apiFetch } from "@/api/client";
import { RangeScopePanel } from "./RangeScopePanel";

it("confirms a range move using its correlation and a public destination UUID", async () => {
  const request = "11111111-1111-1111-1111-111111111111";
  const destination = "22222222-2222-2222-2222-222222222222";
  vi.mocked(apiFetch).mockImplementation(path => Promise.resolve(path.endsWith("range-scoping/") ? { count: 1, next: null, results: [{ request_id: request, owner_id: 1, status: "ready", scenario_id: "synthetic", is_reassignable: true }] } : { changed: true }));
  const user = setupUser();
  renderRoute(<RangeScopePanel workspaceUuid="source" />);
  await user.click(await screen.findByRole("button", { name: "Move synthetic" }));
  await user.type(screen.getByLabelText("Destination workspace UUID"), destination);
  expect(apiFetch).not.toHaveBeenCalledWith(`/cms/ranges/${request}/workspace/`, expect.objectContaining({ method: "POST" }));
  await user.click(screen.getByRole("button", { name: "Confirm range move" }));
  await waitFor(() => expect(apiFetch).toHaveBeenCalledWith(`/cms/ranges/${request}/workspace/`, expect.objectContaining({ method: "POST", body: { target_workspace_uuid: destination } })));
});
