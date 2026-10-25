import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { apiFetch } from "@/api/client";
import type { Adapter } from "@/api/adapters";
import { ApiError } from "@/api/errors";
import { renderRoute } from "@/test/utils";

import { AdapterPackBindings } from "./AdapterPackBindings";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));
const mockApi = vi.mocked(apiFetch);
const adapter: Adapter = {
  id: "installed-1", organization_uuid: "org-1", state: "ready", manifest_digest: "digest", failure_code: "",
  has_registry_credentials: false,
  manifest: { plugin_id: "example.adapter", version: "2", protocol: "shifter.runtime-plugin/v1",
    worker_image: "registry.example.test/image@sha256:digest", capabilities: ["guest.configure", "guest.verify"],
    required_bindings: ["server"], required_parameters: ["mode"], model_bindings: { participant: "server" } },
};
const digest = `sha256:${"a".repeat(64)}`;
const pack = { id: "example", name: "Example pack", pack_digest: digest, binding: null };
const detail = { ...pack, targets: [{ address: "node.web", os_family: "linux" }] };
const base = "/cms/organizations/org-1/plugin-packs/";

beforeEach(() => {
  mockApi.mockReset();
  mockApi.mockImplementation(async (url) => url.includes("?page=")
    ? { count: 1, next: null, previous: null, results: [pack] } : detail);
});

async function fillAssignment() {
  fireEvent.click(await screen.findByRole("button", { name: "Configure Example pack" }));
  fireEvent.change(await screen.findByLabelText("Installed adapter version"), { target: { value: adapter.id } });
  fireEvent.change(screen.getByLabelText("Guest for server"), { target: { value: "node.web" } });
  fireEvent.change(screen.getByLabelText("mode"), { target: { value: "training" } });
}

describe("pack adapter assignments", () => {
  it("provides accessible guest selectors and confirms the exact pack version before saving", async () => {
    const { container } = renderRoute(<AdapterPackBindings organization="org-1" adapters={[adapter]} />);
    await fillAssignment();
    expect(screen.getByText(/Model access for participant will be delivered to node.web/)).toBeInTheDocument();
    const accessibility = await axe(container, { rules: { "color-contrast": { enabled: false } } });
    expect(accessibility.violations).toEqual([]);
    expect(mockApi.mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Review assignment" }));
    fireEvent.click(screen.getByRole("button", { name: "Save assignment" }));
    await waitFor(() => expect(mockApi).toHaveBeenCalledWith(`${base}example/`, { method: "POST", body: {
      installation_id: adapter.id, pack_digest: digest, enabled: true,
      bindings: { targets: { server: "node.web" }, parameters: { mode: "training" }, image_profiles: {} },
    } }));
    expect(await screen.findByText("Assignment saved. Existing ranges keep their original adapter.")).toBeInTheDocument();
  });

  it("lets an administrator bind a machine image and readiness contract", async () => {
    renderRoute(<AdapterPackBindings organization="org-1" adapters={[adapter]} />);
    await fillAssignment();
    fireEvent.click(screen.getByLabelText("Use an administrator-selected provider image for server"));
    fireEvent.change(screen.getByLabelText("Image type for server"), { target: { value: "machine-image" } });
    fireEvent.change(screen.getByLabelText("Image reference for server"), {
      target: { value: "projects/example/global/machineImages/nested-host-v1" },
    });
    fireEvent.change(screen.getByLabelText("Machine type for server"), { target: { value: "e2-standard-8" } });
    fireEvent.change(screen.getByLabelText("Management SSH username for server"), { target: { value: "host-admin" } });
    fireEvent.change(screen.getByLabelText("Participant container for server"), { target: { value: "participant-desktop" } });
    fireEvent.change(screen.getByLabelText("Participant username for server"), { target: { value: "student" } });
    fireEvent.change(screen.getByLabelText("Readiness manifest SHA-256 for server"), { target: { value: "a".repeat(64) } });
    fireEvent.click(screen.getByLabelText("Allow participant public web access (TCP 80/443)"));
    expect(screen.getByRole("button", { name: "Review assignment" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Review assignment" }));
    fireEvent.click(screen.getByRole("button", { name: "Save assignment" }));
    await waitFor(() => {
      const body = mockApi.mock.calls.find(([, options]) => options?.method === "POST")?.[1]?.body as
        | { bindings: { image_profiles: { server: { allow_public_web_egress: boolean } } } }
        | undefined;
      expect(body?.bindings.image_profiles.server.allow_public_web_egress).toBe(true);
    });
  });

  it("lets an administrator bind a preconfigured host from an exact custom image", async () => {
    renderRoute(<AdapterPackBindings organization="org-1" adapters={[adapter]} />);
    await fillAssignment();
    fireEvent.click(screen.getByLabelText("Use an administrator-selected provider image for server"));
    fireEvent.change(screen.getByLabelText("Image reference for server"), {
      target: { value: "projects/example/global/images/nested-host-v1" },
    });
    fireEvent.change(screen.getByLabelText("Bootstrap capability for server"), {
      target: { value: "preconfigured-machine-host" },
    });
    fireEvent.change(screen.getByLabelText("Management SSH username for server"), { target: { value: "host-admin" } });
    fireEvent.change(screen.getByLabelText("Participant container for server"), { target: { value: "participant-desktop" } });
    fireEvent.change(screen.getByLabelText("Participant username for server"), { target: { value: "student" } });
    fireEvent.change(screen.getByLabelText("Readiness manifest SHA-256 for server"), { target: { value: "a".repeat(64) } });
    expect(screen.getByRole("button", { name: "Review assignment" })).toBeEnabled();
  });

  it("clears the GCP web option when switching an assignment to AWS", async () => {
    renderRoute(<AdapterPackBindings organization="org-1" adapters={[adapter]} />);
    await fillAssignment();
    fireEvent.click(screen.getByLabelText("Use an administrator-selected provider image for server"));
    fireEvent.click(screen.getByLabelText("Allow participant public web access (TCP 80/443)"));
    fireEvent.change(screen.getByLabelText("Provider for server"), { target: { value: "aws" } });
    expect(screen.queryByLabelText("Allow participant public web access (TCP 80/443)")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Image reference for server"), { target: { value: "ami-12345678" } });
    expect(screen.getByRole("button", { name: "Review assignment" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Review assignment" }));
    fireEvent.click(screen.getByRole("button", { name: "Save assignment" }));
    await waitFor(() => {
      const body = mockApi.mock.calls.find(([, options]) => options?.method === "POST")?.[1]?.body as
        | { bindings: { image_profiles: { server: { provider: string; allow_public_web_egress: boolean } } } }
        | undefined;
      expect(body?.bindings.image_profiles.server).toMatchObject({ provider: "aws", allow_public_web_egress: false });
    });
  });

  it("lets an administrator bind an AWS preconfigured participant host", async () => {
    renderRoute(<AdapterPackBindings organization="org-1" adapters={[adapter]} />);
    await fillAssignment();
    fireEvent.click(screen.getByLabelText("Use an administrator-selected provider image for server"));
    fireEvent.change(screen.getByLabelText("Provider for server"), { target: { value: "aws" } });
    fireEvent.change(screen.getByLabelText("Image reference for server"), { target: { value: "ami-0123456789abcdef0" } });
    fireEvent.change(screen.getByLabelText("Bootstrap capability for server"), {
      target: { value: "preconfigured-machine-host" },
    });
    expect(screen.getByRole("button", { name: "Review assignment" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Management SSH username for server"), { target: { value: "host-admin" } });
    fireEvent.change(screen.getByLabelText("Management SSH port for server"), { target: { value: "2222" } });
    fireEvent.change(screen.getByLabelText("Participant container for server"), { target: { value: "participant-desktop" } });
    fireEvent.change(screen.getByLabelText("Participant username for server"), { target: { value: "student" } });
    fireEvent.change(screen.getByLabelText("Readiness manifest SHA-256 for server"), { target: { value: "b".repeat(64) } });
    expect(screen.getByRole("button", { name: "Review assignment" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Review assignment" }));
    fireEvent.click(screen.getByRole("button", { name: "Save assignment" }));
    await waitFor(() => {
      const body = mockApi.mock.calls.find(([, options]) => options?.method === "POST")?.[1]?.body as
        | { bindings: { image_profiles: { server: Record<string, unknown> } } }
        | undefined;
      expect(body?.bindings.image_profiles.server).toMatchObject({
        provider: "aws",
        bootstrap_capability: "preconfigured-machine-host",
        participant_container_name: "participant-desktop",
        participant_readiness_contract: "participant-readiness/v1",
        management_ssh_port: 2222,
      });
    });
  });

  it("lets an administrator bind a prepromoted directory image", async () => {
    renderRoute(<AdapterPackBindings organization="org-1" adapters={[adapter]} />);
    await fillAssignment();
    fireEvent.click(screen.getByLabelText("Use an administrator-selected provider image for server"));
    fireEvent.change(screen.getByLabelText("Image reference for server"), {
      target: { value: "projects/example/global/images/directory-v1" },
    });
    fireEvent.change(screen.getByLabelText("Bootstrap capability for server"), {
      target: { value: "prepromoted-domain-controller" },
    });
    fireEvent.change(screen.getByLabelText("Domain DNS name for server"), { target: { value: "example.test" } });
    fireEvent.change(screen.getByLabelText("Domain NetBIOS name for server"), { target: { value: "EXAMPLE" } });
    expect(screen.getByRole("button", { name: "Review assignment" })).toBeEnabled();
  });

  it("keeps a rejected stale assignment open and shows the server's recovery message", async () => {
    mockApi.mockImplementation(async (url, options) => {
      if (options?.method === "POST") throw new ApiError(400, { code: "plugin_invalid", message: "The pack changed; reload its current version before saving" });
      return url.includes("?page=") ? { count: 1, next: null, previous: null, results: [pack] } : detail;
    });
    renderRoute(<AdapterPackBindings organization="org-1" adapters={[adapter]} />);
    await fillAssignment();
    fireEvent.click(screen.getByRole("button", { name: "Review assignment" }));
    fireEvent.click(screen.getByRole("button", { name: "Save assignment" }));
    expect(await screen.findByText("The pack changed; reload its current version before saving")).toBeInTheDocument();
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.queryByText("Assignment saved. Existing ranges keep their original adapter.")).not.toBeInTheDocument();
  });

  it("blocks assignment when the chosen adapter has not passed compatibility checks", async () => {
    renderRoute(<AdapterPackBindings organization="org-1" adapters={[{ ...adapter, state: "checking" }]} />);
    fireEvent.click(await screen.findByRole("button", { name: "Configure Example pack" }));
    await screen.findByLabelText("Installed adapter version");
    expect(screen.getByRole("option", { name: "example.adapter · 2 (checking)" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Review assignment" })).toBeDisabled();
  });
});
