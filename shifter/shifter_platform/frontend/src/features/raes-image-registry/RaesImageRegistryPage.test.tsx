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
    principal: {
      id: 1,
      username: "author",
      display_name: "Author",
      is_authenticated: true,
      is_staff: true,
      is_superuser: false,
    },
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
    management_ssh_port: 22,
    management_ssh_username: "",
    image_kind: "image",
    bootstrap_capability: "standard",
    participant_container_name: "",
    participant_username: "",
    participant_readiness_contract: "",
    participant_readiness_manifest_sha256: "",
    artifact_id: "",
    artifact_version: "",
    artifact_digest: "",
    media_type: "",
    integrity_ref: "",
    provenance_ref: "",
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
    expect(
      await screen.findByText("No image mappings yet"),
    ).toBeInTheDocument();
  });

  it("renders an error state on load failure", async () => {
    mockApi.mockRejectedValue(
      new ApiError(500, { code: "error", message: "boom" }),
    );
    renderRoute(<RaesImageRegistryPage />);
    expect(
      await screen.findByText("Could not load image mappings"),
    ).toBeInTheDocument();
  });

  it("shows the register form for an authoring principal", async () => {
    mockApi.mockResolvedValue([]);
    renderRoute(<RaesImageRegistryPage />);
    expect(
      await screen.findByRole("button", { name: "Register mapping" }),
    ).toBeInTheDocument();
  });

  it("hides the register form and disable actions for a non-authoring viewer", async () => {
    mockBootstrap.mockReturnValue(bootstrapValue(false));
    mockApi.mockResolvedValue([mapping()]);
    renderRoute(<RaesImageRegistryPage />);
    // The list still renders read-only for a non-authoring viewer...
    expect(await screen.findByText("gce:alpine@3.19")).toBeInTheDocument();
    // ...but the authoring affordances are gone.
    expect(
      screen.queryByRole("button", { name: "Register mapping" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("columnheader", { name: "Actions" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Disable" }),
    ).not.toBeInTheDocument();
  });

  it("registers a mapping through the API", async () => {
    let rows: ReturnType<typeof mapping>[] = [];
    mockApi.mockImplementation(
      (_path: string, options?: { method?: string }) => {
        if (options?.method === "POST") {
          rows = [mapping()];
          return Promise.resolve(rows[0]);
        }
        return Promise.resolve(rows);
      },
    );
    renderRoute(<RaesImageRegistryPage />);
    fireEvent.change(await screen.findByLabelText("Source name"), {
      target: { value: "alpine" },
    });
    fireEvent.change(screen.getByLabelText("Image ref"), {
      target: { value: "projects/x/global/images/alpine-3-19" },
    });
    fireEvent.change(screen.getByLabelText("Management SSH username"), {
      target: { value: "image-admin" },
    });
    fireEvent.change(screen.getByLabelText("Management SSH port"), {
      target: { value: "2222" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Register mapping" }));
    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        "/cms/raes-image-mappings/",
        expect.objectContaining({
          method: "POST",
          body: expect.objectContaining({
            source_name: "alpine",
            image_ref: "projects/x/global/images/alpine-3-19",
            management_ssh_port: 2222,
            management_ssh_username: "image-admin",
          }),
        }),
      ),
    );
    expect(await screen.findByText("gce:alpine@3.19")).toBeInTheDocument();
    expect(screen.getByLabelText("Source name")).toHaveValue("");
    expect(screen.getByLabelText("Image ref")).toHaveValue("");
  });

  it("registers a preconfigured machine host profile", async () => {
    mockApi.mockImplementation((_path: string, options?: { method?: string }) =>
      Promise.resolve(options?.method === "POST" ? mapping({ image_kind: "machine-image" }) : []));
    renderRoute(<RaesImageRegistryPage />);
    fireEvent.change(await screen.findByLabelText("Source name"), { target: { value: "nested-host" } });
    fireEvent.click(screen.getByLabelText("Image type"));
    fireEvent.click(screen.getAllByText("Preconfigured machine host").at(-1)!);
    fireEvent.change(screen.getByLabelText("Image ref"), {
      target: { value: "projects/example/global/machineImages/nested-host-v1" },
    });
    fireEvent.change(screen.getByLabelText("Management SSH username"), { target: { value: "host-admin" } });
    fireEvent.change(screen.getByLabelText("Participant container"), { target: { value: "participant-desktop" } });
    fireEvent.change(screen.getByLabelText("Participant username"), { target: { value: "student" } });
    fireEvent.change(screen.getByLabelText("Readiness manifest SHA-256"), { target: { value: "a".repeat(64) } });
    fireEvent.click(screen.getByRole("button", { name: "Register mapping" }));
    await waitFor(() => expect(mockApi).toHaveBeenCalledWith(
      "/cms/raes-image-mappings/",
      expect.objectContaining({ body: expect.objectContaining({
        image_kind: "machine-image",
        bootstrap_capability: "preconfigured-machine-host",
        participant_container_name: "participant-desktop",
        participant_readiness_manifest_sha256: "a".repeat(64),
      }) }),
    ));
  });

  it("registers a preconfigured host from a custom image", async () => {
    mockApi.mockImplementation((_path: string, options?: { method?: string }) =>
      Promise.resolve(options?.method === "POST" ? mapping({ image_kind: "image" }) : []));
    renderRoute(<RaesImageRegistryPage />);
    fireEvent.change(await screen.findByLabelText("Source name"), { target: { value: "nested-host" } });
    fireEvent.click(screen.getByLabelText("Preconfigured participant host"));
    fireEvent.change(screen.getByLabelText("Image ref"), {
      target: { value: "projects/example/global/images/nested-host-v1" },
    });
    fireEvent.change(screen.getByLabelText("Management SSH username"), { target: { value: "host-admin" } });
    fireEvent.change(screen.getByLabelText("Participant container"), { target: { value: "participant-desktop" } });
    fireEvent.change(screen.getByLabelText("Participant username"), { target: { value: "student" } });
    fireEvent.change(screen.getByLabelText("Readiness manifest SHA-256"), { target: { value: "a".repeat(64) } });
    fireEvent.click(screen.getByRole("button", { name: "Register mapping" }));
    await waitFor(() => expect(mockApi).toHaveBeenCalledWith(
      "/cms/raes-image-mappings/",
      expect.objectContaining({ body: expect.objectContaining({
        image_kind: "image",
        bootstrap_capability: "preconfigured-machine-host",
        participant_container_name: "participant-desktop",
      }) }),
    ));
  });

  it("disables a mapping through the API", async () => {
    let rows = [mapping()];
    mockApi.mockImplementation(
      (_path: string, options?: { method?: string }) => {
        if (options?.method === "POST") {
          rows = [mapping({ enabled: false })];
          return Promise.resolve(rows[0]);
        }
        return Promise.resolve(rows);
      },
    );
    renderRoute(<RaesImageRegistryPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Disable" }));
    await waitFor(() =>
      expect(mockApi).toHaveBeenCalledWith(
        "/cms/raes-image-mappings/disable/",
        expect.objectContaining({
          method: "POST",
          body: expect.objectContaining({
            provider: "gce",
            source_name: "alpine",
            source_version: "3.19",
          }),
        }),
      ),
    );
    expect(await screen.findByText("Disabled")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Disable" }),
    ).not.toBeInTheDocument();
  });

  it("has no axe violations when loaded", async () => {
    mockApi.mockResolvedValue([mapping()]);
    const { container } = renderRoute(<RaesImageRegistryPage />);
    await screen.findByText("gce:alpine@3.19");
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});
