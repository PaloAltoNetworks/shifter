import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));
import { apiFetch } from "@/api/client";
import { AccessCredentialsPage } from "./AccessCredentialsPage";

it("delivers a personal secret only in component memory, outside query and mutation caches", async () => {
  vi.mocked(apiFetch).mockImplementation(async (path, options) => {
    if (path.includes("catalog")) return [{ code: "installation.read_audit", target_type: "installation" }];
    if (options?.method === "POST") return { credential_uuid: "credential", token: "one-time-secret" };
    return { count: 0, next_offset: null, results: [] };
  });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={queryClient}><AccessCredentialsPage /></QueryClientProvider>);
  fireEvent.change(screen.getByLabelText("Token name"), { target: { value: "Audit reader" } });
  fireEvent.change(screen.getByLabelText("Expires at"), { target: { value: "2030-01-01T12:00" } });
  await screen.findByRole("option", { name: "installation.read_audit" });
  fireEvent.change(screen.getByLabelText("Token action"), { target: { value: "installation.read_audit" } });
  fireEvent.click(screen.getByRole("button", { name: "Issue token" }));
  expect(await screen.findByDisplayValue("one-time-secret")).toBeInTheDocument();
  expect(JSON.stringify(queryClient.getQueryCache().getAll().map(item => item.state.data))).not.toContain("one-time-secret");
  expect(queryClient.getMutationCache().getAll()).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Dismiss secret" }));
  await waitFor(() => expect(screen.queryByDisplayValue("one-time-secret")).not.toBeInTheDocument());
});
