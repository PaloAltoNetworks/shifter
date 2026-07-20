import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";

import { ApiError } from "@/api/errors";
import type { NGFWDestroyResponse, NGFWListResponse } from "@/api/types";
import { renderRoute } from "@/test/utils";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

import { apiFetch } from "@/api/client";

import { NgfwListPage } from "./NgfwListPage";

const mockApi = vi.mocked(apiFetch);

const NGFWS: NGFWListResponse = {
  ngfws: [
    {
      id: "11111111-1111-1111-1111-111111111111",
      name: "lab-ngfw",
      status: "ready",
      created_at: "2026-07-01T00:00:00Z",
      serial_number: "000000000000",
    },
  ],
};

function selectNgfwList() {
  mockApi.mockImplementation((path: string) => {
    if (path === "/mission-control/ngfw/list/") return Promise.resolve(NGFWS);
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

beforeEach(() => {
  mockApi.mockReset();
});

describe("NgfwListPage", () => {
  it("shows a loading skeleton while NGFWs load", () => {
    mockApi.mockReturnValue(new Promise(() => {}));
    const { container } = renderRoute(<NgfwListPage />);
    expect(container.querySelectorAll('[data-slot="skeleton"]').length).toBeGreaterThan(0);
  });

  it("shows an error when NGFWs fail to load", async () => {
    mockApi.mockRejectedValue(new ApiError(500, { code: "error", message: "boom" }));
    renderRoute(<NgfwListPage />);
    expect(await screen.findByText("Could not load your NGFWs")).toBeInTheDocument();
  });

  it("shows an empty state with a setup link when there are no NGFWs", async () => {
    mockApi.mockResolvedValue({ ngfws: [] } satisfies NGFWListResponse);
    renderRoute(<NgfwListPage />);
    expect(await screen.findByText("No NGFWs configured")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Set up NGFW" }).length).toBeGreaterThan(0);
  });

  it("lists NGFWs with a detail link, status, and a setup link in the header", async () => {
    selectNgfwList();
    renderRoute(<NgfwListPage />);

    const link = await screen.findByRole("link", { name: "lab-ngfw" });
    expect(link).toHaveAttribute("href", "/mission-control/ngfw/11111111-1111-1111-1111-111111111111/");
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Set up NGFW" })).toHaveAttribute(
      "href",
      "/mission-control/ngfw/setup/",
    );
  });

  it("destroys an NGFW behind the type-to-confirm dialog and refreshes the list", async () => {
    selectNgfwList();
    const user = userEvent.setup();
    renderRoute(<NgfwListPage />);

    await user.click(await screen.findByRole("button", { name: "Deprovision" }));
    expect(await screen.findByText("Deprovision lab-ngfw")).toBeInTheDocument();

    const confirmButton = screen.getByRole("button", { name: "Deprovision NGFW" });
    expect(confirmButton).toBeDisabled();

    mockApi.mockImplementation((path: string) => {
      if (path === "/mission-control/ngfw/list/") return Promise.resolve(NGFWS);
      if (path === "/mission-control/ngfw/11111111-1111-1111-1111-111111111111/destroy/") {
        return Promise.resolve({ status: "deprovisioning" } satisfies NGFWDestroyResponse);
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    await user.type(screen.getByLabelText(/Type/), "lab-ngfw");
    await user.click(screen.getByRole("button", { name: "Deprovision NGFW" }));

    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith("/mission-control/ngfw/11111111-1111-1111-1111-111111111111/destroy/", {
        method: "POST",
        body: { confirm_name: "lab-ngfw" },
      }),
    );
    await waitFor(() => expect(screen.queryByText("Deprovision lab-ngfw")).not.toBeInTheDocument());
  });

  it("has no axe violations once NGFWs are loaded", async () => {
    selectNgfwList();
    const { container } = renderRoute(<NgfwListPage />);
    await screen.findByRole("link", { name: "lab-ngfw" });
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});
