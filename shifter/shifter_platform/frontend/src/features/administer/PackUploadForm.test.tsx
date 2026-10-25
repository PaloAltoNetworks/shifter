import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import type { AdapterPack } from "@/api/adapter-packs";
import { apiFetch } from "@/api/client";
import { ApiError } from "@/api/errors";
import { renderRoute } from "@/test/utils";

import { PackUploadForm } from "./PackUploadForm";

vi.mock("@/api/client", () => ({ apiFetch: vi.fn() }));
const mockApi = vi.mocked(apiFetch);
const digest = `sha256:${"a".repeat(64)}`;
const pack: AdapterPack = { id: "pack-example", name: "example", pack_digest: digest, can_update: true, binding: null };

beforeEach(() => {
  mockApi.mockReset();
  mockApi.mockResolvedValue({ name: "example", package_version: "1.0.0" });
});

function chooseArchive() {
  const archive = new File(["synthetic archive"], "example.tar.gz", { type: "application/gzip" });
  fireEvent.change(screen.getByLabelText("Pack archive (.tar or .tar.gz)"), { target: { files: [archive] } });
  return archive;
}

describe("tenant content upload", () => {
  it("confirms installation and submits multipart bytes through the tenant endpoint", async () => {
    const { container } = renderRoute(<PackUploadForm organization="org-1" packs={[]} />);
    expect(screen.getByRole("button", { name: "Review pack installation" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Pack name"), { target: { value: "example" } });
    const archive = chooseArchive();
    expect((await axe(container, { rules: { "color-contrast": { enabled: false } } })).violations).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Review pack installation" }));
    expect(mockApi).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Install pack" }));
    await waitFor(() => expect(mockApi).toHaveBeenCalledTimes(1));
    const [url, options] = mockApi.mock.calls[0];
    expect(url).toBe("/cms/organizations/org-1/packs/");
    expect(options?.method).toBe("POST");
    const body = options?.body as FormData;
    expect(body.get("name")).toBe("example");
    expect(body.get("archive")).toBe(archive);
    expect(body.has("expected_digest")).toBe(false);
    expect(await screen.findByRole("status")).toHaveTextContent("Installed example version 1.0.0");
    expect(screen.getByRole("button", { name: "Review pack installation" })).toBeDisabled();
  });

  it("pins an update to the displayed revision and retains rejected updates for recovery", async () => {
    mockApi.mockRejectedValue(new ApiError(400, { code: "invalid", message: "Reload the current version and retry" }));
    renderRoute(<PackUploadForm organization="org-1" packs={[pack, { ...pack, id: "shared", name: "shared", can_update: false }]} />);
    expect(screen.queryByRole("option", { name: "Update shared" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Installation"), { target: { value: pack.id } });
    expect(screen.getByLabelText("Pack name")).toBeDisabled();
    chooseArchive();
    fireEvent.click(screen.getByRole("button", { name: "Review pack installation" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Existing ranges keep their original version");
    fireEvent.click(screen.getByRole("button", { name: "Install pack" }));
    expect(await screen.findByText("Reload the current version and retry")).toBeInTheDocument();
    expect((mockApi.mock.calls[0][1]?.body as FormData).get("expected_digest")).toBe(digest);
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
