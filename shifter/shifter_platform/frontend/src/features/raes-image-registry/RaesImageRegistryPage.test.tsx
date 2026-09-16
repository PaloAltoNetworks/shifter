import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { axe } from "vitest-axe";

import { ApiError } from "@/api/errors";
import { renderRoute } from "@/test/utils";

const { mockBootstrap } = vi.hoisted(() => ({ mockBootstrap: vi.fn() }));

vi.mock("@/app/bootstrap-context", () => ({
  useBootstrapContext: () => mockBootstrap(),
}));

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));

function bootstrapValue(canAuthor = true) {
  return {
    principal: { id: 1, username: "author", display_name: "Author", is_authenticated: true, is_staff: true, is_superuser: false },
    permissions: { can_access_threat_research: canAuthor },
  };
}

import { apiFetch } from "@/api/client";

import { RaesImageRegistryPage } from "./RaesImageRegistryPage";

const mockApi = vi.mocked(apiFetch);

function mapping(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    provider: "gce",
    source_name: "alpine",
    source_version: "3.19",
    image_ref: "projects/x/global/images/alpine-3-19",
    machine_type: "",
    disk_size_gb: null,
    disk_type: "",
    enabled: true,
    notes: "",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  mockApi.mockReset();
  mockBootstrap.mockReset();
  mockBootstrap.mockReturnValue(bootstrapValue(true));
});

describe("RaesImageRegistryPage", () => {
  it("renders mapping rows", async () => {
    mockApi.mockResolvedValue([mapping()]);
    renderRoute(<RaesImageRegistryPage />);
    expect(await screen.findByText("gce:alpine@3.19")).toBeInTheDocument();
    expect(screen.getByText("Enabled")).toBeInTheDocument();
  });

  it("shows the empty state when the registry is empty", async () => {
    mockApi.mockResolvedValue([]);
    renderRoute(<RaesImageRegistryPage />);
    expect(await screen.findByText("No image mappings yet")).toBeInTheDocument();
  });

  it("renders an error state on load failure", async () => {
    mockApi.mockRejectedValue(new ApiError(500, { code: "error", message: "boom" }));
    renderRoute(<RaesImageRegistryPage />);
    expect(await screen.findByText("Could not load image mappings")).toBeInTheDocument();
  });

  it("shows the register form for an authoring principal", async () => {
    mockApi.mockResolvedValue([]);
    renderRoute(<RaesImageRegistryPage />);
    expect(await screen.findByRole("button", { name: "Register mapping" })).toBeInTheDocument();
  });

  it("hides the register form and disable actions for a non-authoring viewer", async () => {
    mockBootstrap.mockReturnValue(bootstrapValue(false));
    mockApi.mockResolvedValue([mapping()]);
    renderRoute(<RaesImageRegistryPage />);
    // The list still renders read-only for a non-authoring viewer...
    expect(await screen.findByText("gce:alpine@3.19")).toBeInTheDocument();
    // ...but the authoring affordances are gone.
    expect(screen.queryByRole("button", { name: "Register mapping" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Actions" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Disable" })).not.toBeInTheDocument();
  });

  it("registers a mapping through the API", async () => {
    let rows: ReturnType<typeof mapping>[] = [];
    mockApi.mockImplementation((_path: string, options?: { method?: string }) => {
      if (options?.method === "POST") {
        rows = [mapping()];
        return Promise.resolve(rows[0]);
      }
      return Promise.resolve(rows);
    });
    renderRoute(<RaesImageRegistryPage />);
    fireEvent.change(await screen.findByLabelText("Source name"), { target: { value: "alpine" } });
    fireEvent.change(screen.getByLabelText("Image ref"), {
      target: { value: "projects/x/global/images/alpine-3-19" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Register mapping" }));
    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        "/cms/raes-image-mappings/",
        expect.objectContaining({
          method: "POST",
          body: expect.objectContaining({ source_name: "alpine", image_ref: "projects/x/global/images/alpine-3-19" }),
        }),
      ),
    );
    expect(await screen.findByText("gce:alpine@3.19")).toBeInTheDocument();
    expect(screen.getByLabelText("Source name")).toHaveValue("");
    expect(screen.getByLabelText("Image ref")).toHaveValue("");
  });

  it("disables a mapping through the API", async () => {
    let rows = [mapping()];
    mockApi.mockImplementation((_path: string, options?: { method?: string }) => {
      if (options?.method === "POST") {
        rows = [mapping({ enabled: false })];
        return Promise.resolve(rows[0]);
      }
      return Promise.resolve(rows);
    });
    renderRoute(<RaesImageRegistryPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Disable" }));
    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        "/cms/raes-image-mappings/disable/",
        expect.objectContaining({
          method: "POST",
          body: expect.objectContaining({ provider: "gce", source_name: "alpine", source_version: "3.19" }),
        }),
      ),
    );
    expect(await screen.findByText("Disabled")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Disable" })).not.toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue([mapping()]);
    const { container } = renderRoute(<RaesImageRegistryPage />);
    await screen.findByText("gce:alpine@3.19");
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});
