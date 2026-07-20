import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";

import { ApiError } from "@/api/errors";
import type { GuacamoleBootstrapQueued, GuacamoleBootstrapStatus, NGFWDestroyResponse, NGFWListResponse } from "@/api/types";
import { renderRoute } from "@/test/utils";

const navigateMock = vi.fn();
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => navigateMock };
});

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { NgfwDetailPage } from "./NgfwDetailPage";

const mockApi = vi.mocked(apiFetch);

const READY_APP_ID = "11111111-1111-1111-1111-111111111111";
const PROVISIONING_APP_ID = "22222222-2222-2222-2222-222222222222";

const NGFWS: NGFWListResponse = {
  ngfws: [
    { id: READY_APP_ID, name: "lab-ngfw", status: "ready", created_at: "2026-07-01T00:00:00Z", serial_number: "000000000000" },
    { id: PROVISIONING_APP_ID, name: "new-ngfw", status: "provisioning", created_at: "2026-07-02T00:00:00Z", serial_number: null },
  ],
};

function selectNgfwList() {
  mockApi.mockImplementation((path: string) => {
    if (path === "/mission-control/ngfw/list/") return Promise.resolve(NGFWS);
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

function renderDetail(appId: string) {
  return renderRoute(<NgfwDetailPage />, { path: "/mission-control/ngfw/:appId", initialEntries: [`/mission-control/ngfw/${appId}`] });
}

let openSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockApi.mockReset();
  navigateMock.mockReset();
  openSpy = vi.fn();
  vi.stubGlobal("open", openSpy);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("NgfwDetailPage", () => {
  it("shows a loading skeleton while the NGFW list loads", () => {
    mockApi.mockReturnValue(new Promise(() => {}));
    const { container } = renderDetail(READY_APP_ID);
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(0);
  });

  it("shows an error when the NGFW list fails to load", async () => {
    mockApi.mockRejectedValue(new ApiError(500, { code: "error", message: "boom" }));
    renderDetail(READY_APP_ID);
    expect(await screen.findByText("Could not load this NGFW")).toBeInTheDocument();
  });

  it("shows a not-found state for an unknown app id", async () => {
    selectNgfwList();
    renderDetail("99999999-9999-9999-9999-999999999999");
    expect(await screen.findByText("NGFW not found")).toBeInTheDocument();
  });

  it("renders metadata for a provisioning NGFW without a CLI access card", async () => {
    selectNgfwList();
    renderDetail(PROVISIONING_APP_ID);

    expect(await screen.findByRole("heading", { name: "new-ngfw" })).toBeInTheDocument();
    expect(screen.getByText("Pending provisioning")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open cli/i })).not.toBeInTheDocument();
  });

  it("opens a CLI SSH session for a ready NGFW via the app-id-keyed bootstrap", async () => {
    const queued: GuacamoleBootstrapQueued = {
      request_id: "33333333-3333-3333-3333-333333333333",
      status: "PENDING",
      status_url: "/api/v1/mission-control/guacamole/bootstrap/33333333-3333-3333-3333-333333333333/",
      url: "",
    };
    const succeeded: GuacamoleBootstrapStatus = {
      request_id: queued.request_id,
      status: "SUCCEEDED",
      url: "https://guac.example.test/session/ngfw?token=SECRET",
    };
    selectNgfwList();
    const user = userEvent.setup();
    renderDetail(READY_APP_ID);

    await screen.findByText("000000000000");

    mockApi.mockImplementation((path: string) => {
      if (path === "/mission-control/ngfw/list/") return Promise.resolve(NGFWS);
      if (path === `/mission-control/ngfw/${READY_APP_ID}/ssh-url/`) return Promise.resolve(queued);
      if (path === `/mission-control/guacamole/bootstrap/${queued.request_id}/`) return Promise.resolve(succeeded);
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    await user.click(screen.getByRole("button", { name: "Open CLI" }));

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(`/mission-control/ngfw/${READY_APP_ID}/ssh-url/`, { method: "POST" }),
    );
    await waitFor(() => expect(openSpy).toHaveBeenCalledWith(succeeded.url, "_blank", "noopener,noreferrer"));
  });

  it("deprovisions the NGFW from the danger zone and navigates back to the list", async () => {
    selectNgfwList();
    const user = userEvent.setup();
    renderDetail(READY_APP_ID);

    await user.click(await screen.findByRole("button", { name: "Deprovision NGFW" }));
    expect(await screen.findByText("Deprovision lab-ngfw")).toBeInTheDocument();

    mockApi.mockImplementation((path: string) => {
      if (path === "/mission-control/ngfw/list/") return Promise.resolve(NGFWS);
      if (path === `/mission-control/ngfw/${READY_APP_ID}/destroy/`) {
        return Promise.resolve({ status: "deprovisioning" } satisfies NGFWDestroyResponse);
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    await user.type(screen.getByLabelText(/Type/), "lab-ngfw");
    await user.click(screen.getByRole("button", { name: "Deprovision NGFW" }));

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(`/mission-control/ngfw/${READY_APP_ID}/destroy/`, {
        method: "POST",
        body: { confirm_name: "lab-ngfw" },
      }),
    );
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/mission-control/ngfw/"));
  });

  it("has no axe violations for a ready NGFW", async () => {
    selectNgfwList();
    const { container } = renderDetail(READY_APP_ID);
    await screen.findByText("000000000000");
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});
